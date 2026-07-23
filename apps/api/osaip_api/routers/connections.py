"""Connections CRUD + test (Phase 1). Admin-only management (credentials!);
secret values are write-only; driver errors surface only as sanitized engine
exceptions translated here (ADR-0006 §4)."""

import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.idempotency import check_idempotency, store_idempotent_response
from osaip_api.models import Connection, Dataset, Secret
from osaip_api.permissions import ProjectContext, load_project_context
from osaip_api.problem import Problem
from osaip_api.schemas import ConnectionListOut, ConnectionOut, ConnectionTestOut
from osaip_api.secrets import Vault
from osaip_engine import pg
from osaip_engine.errors import (
    AuthFailed,
    DatabaseNotFound,
    EngineError,
    HostUnreachable,
)
from osaip_shared.ids import new_id

router = APIRouter(prefix="/projects/{key}/connections", tags=["connections"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

_HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.$-]{1,63}$")


class PostgresConfig(BaseModel):
    host: str
    port: int = Field(default=5432, ge=1, le=65535)
    database: str
    user: str

    @field_validator("host")
    @classmethod
    def _host(cls, value: str) -> str:
        if not _HOST_RE.match(value):
            raise ValueError("host must be a hostname or IP (letters, digits, dots, dashes)")
        return value

    @field_validator("database", "user")
    @classmethod
    def _ident(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError("only letters, digits, and _.$- are allowed")
        return value


class S3Config(BaseModel):
    endpoint: str = Field(description="host:port, scheme-less")
    bucket: str
    region: str = "us-east-1"
    use_ssl: bool = False
    access_key: str = Field(min_length=1, max_length=200)

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, value: str) -> str:
        if "://" in value or not re.match(r"^[A-Za-z0-9._-]+(:\d{1,5})?$", value):
            raise ValueError("endpoint must be host or host:port without a scheme")
        return value

    @field_validator("bucket")
    @classmethod
    def _bucket(cls, value: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", value):
            raise ValueError("not a valid S3 bucket name")
        return value


class DuckdbFileConfig(BaseModel):
    path: str = Field(
        description="s3:// URI of a .duckdb file inside this project's storage prefix"
    )

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if not value.startswith("s3://") or ".." in value or not value.endswith(".duckdb"):
            raise ValueError("path must be an s3:// URI of a .duckdb file, without '..'")
        return value


_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "postgres": PostgresConfig,
    "s3": S3Config,
    "duckdb_file": DuckdbFileConfig,
}


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["postgres", "s3", "duckdb_file"]
    config: dict[str, Any]
    secret: str | None = Field(default=None, max_length=10_000, description="write-only")
    legal_basis: str = Field(min_length=1, max_length=500, description="CP-2")
    purpose_codes: list[str] = Field(min_length=1, max_length=20, description="CP-2")


class ConnectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None
    secret: str | None = Field(default=None, max_length=10_000)
    legal_basis: str | None = Field(default=None, min_length=1, max_length=500)
    purpose_codes: list[str] | None = Field(default=None, min_length=1, max_length=20)


def _validated_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    try:
        return _CONFIG_MODELS[kind].model_validate(config).model_dump()
    except ValueError as exc:
        raise Problem(
            422,
            title="Invalid connection config",
            detail=str(exc),
            hint="Fix the highlighted fields for this connection kind and retry.",
            slug="validation",
        ) from exc


def _deny_platform_db(request: Request, kind: str, config: dict[str, Any]) -> None:
    """SSRF guard (plan §6): the platform's own metadata DB is never a valid target."""
    if kind != "postgres":
        return
    url = urlsplit(request.app.state.settings.database_url.replace("+asyncpg", ""))
    if (
        config["host"] == (url.hostname or "")
        and int(config["port"]) == (url.port or 5432)
        and config["database"] == url.path.lstrip("/")
    ):
        raise Problem(
            422,
            title="Target not allowed",
            detail="This is the platform's own metadata database.",
            hint="Point the connection at a data source, not at OSAIP's internal database.",
            slug="target-not-allowed",
        )


def _payload(connection: Connection) -> dict[str, Any]:
    return {
        "id": str(connection.id),
        "name": connection.name,
        "kind": connection.kind,
        "config": connection.config,
        "has_secret": connection.secret_id is not None,
        "legal_basis": connection.legal_basis,
        "purpose_codes": connection.purpose_codes,
        "status": connection.status,
        "created_at": connection.created_at.isoformat(),
        "updated_at": connection.updated_at.isoformat(),
    }


async def _get_connection(
    session: AsyncSession, ctx: ProjectContext, connection_id: str
) -> Connection:
    connection = (
        await session.execute(
            select(Connection).where(
                Connection.id == connection_id, Connection.project_id == ctx.project.id
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise Problem(
            404,
            title="Connection not found",
            detail="No such connection in this project.",
            hint="Check the connection id.",
            slug="not-found",
        )
    return connection


async def _store_secret(
    session: AsyncSession, vault: Vault, ctx: ProjectContext, connection: Connection, value: str
) -> None:
    if connection.secret_id is not None:
        secret = (
            await session.execute(select(Secret).where(Secret.id == connection.secret_id))
        ).scalar_one()
        secret.ciphertext = vault.encrypt(value)
        secret.key_id = vault.primary_key_id
    else:
        secret = Secret(
            id=new_id(),
            project_id=ctx.project.id,
            name=f"connection:{connection.name}",
            ciphertext=vault.encrypt(value),
            key_id=vault.primary_key_id,
        )
        session.add(secret)
        await session.flush()
        connection.secret_id = secret.id


async def _decrypted_secret(
    session: AsyncSession, vault: Vault, connection: Connection
) -> str | None:
    if connection.secret_id is None:
        return None
    secret = (
        await session.execute(select(Secret).where(Secret.id == connection.secret_id))
    ).scalar_one()
    return vault.decrypt(secret.ciphertext)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=ConnectionListOut)
async def list_connections(key: str, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    rows = (
        (
            await session.execute(
                select(Connection)
                .where(Connection.project_id == ctx.project.id)
                .order_by(Connection.name)
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_payload(row) for row in rows]}


@router.post("", status_code=201, response_model=ConnectionOut)
async def create_connection(
    key: str, body: ConnectionCreate, request: Request, user: CurrentUser, session: DbSession
) -> JSONResponse:
    ctx = await load_project_context(session, user, key, min_role="admin")
    idem_body = body.model_dump()
    idem_key, req_hash, stored = await check_idempotency(session, request, user, idem_body)
    if stored is not None:
        return JSONResponse(content=stored[1], status_code=stored[0])

    config = _validated_config(body.kind, body.config)
    _deny_platform_db(request, body.kind, config)
    duplicate = (
        await session.execute(
            select(Connection).where(
                Connection.project_id == ctx.project.id, Connection.name == body.name
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise Problem(
            409,
            title="Name already in use",
            detail=f"A connection named {body.name!r} already exists in this project.",
            hint="Pick a different name.",
            slug="conflict",
        )

    connection = Connection(
        id=new_id(),
        project_id=ctx.project.id,
        name=body.name,
        kind=body.kind,
        config=config,
        legal_basis=body.legal_basis,
        purpose_codes=body.purpose_codes,
        created_by=user.id,
    )
    session.add(connection)
    await session.flush()
    if body.secret:
        await _store_secret(session, request.app.state.vault, ctx, connection, body.secret)

    payload = _payload(connection)
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="connection.created",
        object_kind="connection",
        object_id=str(connection.id),
        details={"name": body.name, "kind": body.kind},
        ip=_client_ip(request),
    )
    if idem_key:
        await store_idempotent_response(session, user, idem_key, request, req_hash, 201, payload)
    await session.commit()
    return JSONResponse(content=payload, status_code=201)


@router.get("/{connection_id}", response_model=ConnectionOut)
async def get_connection(
    key: str, connection_id: str, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    return _payload(await _get_connection(session, ctx, connection_id))


@router.patch("/{connection_id}", response_model=ConnectionOut)
async def patch_connection(
    key: str,
    connection_id: str,
    body: ConnectionPatch,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="admin")
    connection = await _get_connection(session, ctx, connection_id)
    changed: list[str] = []
    if body.name is not None and body.name != connection.name:
        connection.name = body.name
        changed.append("name")
    if body.config is not None:
        config = _validated_config(connection.kind, body.config)
        _deny_platform_db(request, connection.kind, config)
        connection.config = config
        changed.append("config")
    if body.legal_basis is not None:
        connection.legal_basis = body.legal_basis
        changed.append("legal_basis")
    if body.purpose_codes is not None:
        connection.purpose_codes = body.purpose_codes
        changed.append("purpose_codes")
    if body.secret:
        await _store_secret(session, request.app.state.vault, ctx, connection, body.secret)
        changed.append("secret")  # the value itself is never audited

    payload = _payload(connection)
    if changed:
        await write_audit(
            session,
            actor_id=user.id,
            project_id=ctx.project.id,
            action="connection.updated",
            object_kind="connection",
            object_id=str(connection.id),
            details={"changed": changed},
            ip=_client_ip(request),
        )
    await session.commit()
    return payload


@router.delete("/{connection_id}", response_model=ConnectionOut)
async def archive_connection(
    key: str, connection_id: str, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="admin")
    connection = await _get_connection(session, ctx, connection_id)
    in_use = (
        await session.execute(
            select(func.count())
            .select_from(Dataset)
            .where(Dataset.connection_id == connection.id, Dataset.status == "active")
        )
    ).scalar_one()
    if in_use:
        raise Problem(
            409,
            title="Connection is in use",
            detail=f"{in_use} active dataset(s) still use this connection.",
            hint="Archive or re-point those datasets first.",
            slug="conflict",
        )
    connection.status = "archived"
    payload = _payload(connection)
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="connection.archived",
        object_kind="connection",
        object_id=str(connection.id),
        details={"name": connection.name},
        ip=_client_ip(request),
    )
    await session.commit()
    return payload


@router.post("/{connection_id}/test", response_model=ConnectionTestOut)
async def test_connection(
    key: str, connection_id: str, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="admin")
    connection = await _get_connection(session, ctx, connection_id)
    secret = await _decrypted_secret(session, request.app.state.vault, connection)
    try:
        if connection.kind == "postgres":
            latency = await pg.test_connection(
                pg.PgTarget(
                    host=connection.config["host"],
                    port=connection.config["port"],
                    database=connection.config["database"],
                    user=connection.config["user"],
                    password=secret or "",
                )
            )
        else:
            # s3 / duckdb_file tests land with the storage slice.
            raise Problem(
                400,
                title="Test not available yet",
                detail=f"Testing {connection.kind} connections is not implemented yet.",
                hint="This arrives with the storage engine slice of Phase 1.",
                slug="not-implemented",
            )
    except EngineError as exc:
        raise _engine_problem(exc) from exc
    return {"ok": True, "latency_ms": round(latency, 1)}


def _engine_problem(exc: EngineError) -> Problem:
    slug = {
        AuthFailed: "connection-auth-failed",
        HostUnreachable: "connection-unreachable",
        DatabaseNotFound: "connection-db-not-found",
    }.get(type(exc), "connection-failed")
    return Problem(
        400,
        title="Connection test failed",
        detail=exc.public_message,  # sanitized by construction (ADR-0006 §4)
        hint="Fix the connection settings or credentials and test again.",
        slug=slug,
    )
