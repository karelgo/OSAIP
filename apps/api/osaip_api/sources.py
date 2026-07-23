"""Shared resolution of connections → engine targets, with the §8 confinement
checks (identifier validation, path containment) and engine→problem translation."""

from typing import Any

from osaip_api.models import Connection
from osaip_api.problem import Problem
from osaip_engine import duck
from osaip_engine.errors import (
    AuthFailed,
    DatabaseNotFound,
    EngineError,
    HostUnreachable,
    Interrupted,
    ObjectNotFound,
)
from osaip_engine.safety import is_plain_ident
from osaip_engine.storage import StorageConfig


def engine_problem(exc: EngineError) -> Problem:
    slug = {
        AuthFailed: "connection-auth-failed",
        HostUnreachable: "connection-unreachable",
        DatabaseNotFound: "connection-db-not-found",
        ObjectNotFound: "connection-object-not-found",
        Interrupted: "engine-timeout",
    }.get(type(exc), "connection-failed")
    return Problem(
        400,
        title="Data source error",
        detail=exc.public_message,  # sanitized by construction (ADR-0006 §4)
        hint="Fix the connection settings, credentials, or target and try again.",
        slug=slug,
    )


def validate_table_name(table: str) -> str:
    parts = table.split(".")
    if len(parts) > 2 or not all(is_plain_ident(part) for part in parts):
        raise Problem(
            422,
            title="Invalid table name",
            detail="Expected `table` or `schema.table` using letters, digits, _ and $.",
            hint="Check the table name; quoting/special characters are not supported yet.",
            slug="validation",
        )
    return table


def validate_rel_path(path: str, *, suffix: str) -> str:
    if (
        ".." in path
        or path.startswith("/")
        or "//" in path
        or not path.endswith(suffix)
        or len(path) > 900
    ):
        raise Problem(
            422,
            title="Invalid path",
            detail=f"Expected a relative path ending in {suffix}, without '..'.",
            hint="Use a plain relative object path inside the bucket.",
            slug="validation",
        )
    return path


def pg_target(connection: Connection, secret: str | None) -> duck.PgAttach:
    config: dict[str, Any] = connection.config
    return duck.PgAttach(
        host=config["host"],
        port=int(config["port"]),
        database=config["database"],
        user=config["user"],
        password=secret or "",
    )


def s3_config(connection: Connection, secret: str | None) -> StorageConfig:
    config: dict[str, Any] = connection.config
    return StorageConfig(
        endpoint=config["endpoint"],
        bucket=config["bucket"],
        access_key=config["access_key"],
        secret_key=secret or "",
        region=config.get("region", "us-east-1"),
        use_ssl=bool(config.get("use_ssl", False)),
    )


def contained_duckdb_uri(platform_bucket: str, project_key: str, path: str) -> str:
    """A duckdb_file connection's path must be an s3:// URI inside THIS project's
    prefix on the platform bucket (plan §6)."""
    required = f"s3://{platform_bucket}/projects/{project_key}/"
    if not path.startswith(required) or ".." in path:
        raise Problem(
            422,
            title="Path outside project storage",
            detail="duckdb_file paths must live inside this project's storage prefix.",
            hint=f"Use a path under {required}.",
            slug="target-not-allowed",
        )
    return path
