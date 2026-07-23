"""DuckDB adapter: connection factory, schema inference, conversion, sampling,
profiling, and read-only Postgres attach. All functions are BLOCKING — callers in
async apps route them through osaip_engine.aio.run_engine (ADR-0006 §4).
"""

import datetime
import decimal
import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

import duckdb

from osaip_engine.errors import (
    AuthFailed,
    DatabaseNotFound,
    HostUnreachable,
    Interrupted,
    InvalidInput,
    ObjectNotFound,
)
from osaip_engine.safety import qualified_ident, sql_literal
from osaip_engine.storage import StorageConfig

# Extensions are baked into this directory at Docker build; host dev/CI may still
# download on first use (network needed there — documented in the plan).
EXTENSION_DIR = os.environ.get("OSAIP_DUCKDB_EXTENSION_DIR")
MEMORY_LIMIT = os.environ.get("OSAIP_DUCKDB_MEMORY_LIMIT", "1GB")
DUCKDB_THREADS = os.environ.get("OSAIP_DUCKDB_THREADS", "2")
DEFAULT_TIMEOUT_S = 60.0

_S3_EXTENSIONS = ("httpfs",)


@dataclass
class Column:
    name: str
    type: str
    nullable: bool = True


@dataclass
class InferResult:
    columns: list[Column]
    preview: list[dict[str, Any]]
    params: dict[str, Any] = field(default_factory=dict)


def install_extensions() -> None:
    """Explicit one-time install (Docker bake, test session setup, seed start).
    Runtime connections never auto-install (ADR-0006 §3)."""
    config: dict[str, Any] = {}
    if EXTENSION_DIR:
        config["extension_directory"] = EXTENSION_DIR
    conn = duckdb.connect(":memory:", config=config)
    try:
        for extension in ("httpfs", "postgres", "excel"):
            conn.install_extension(extension)
    finally:
        conn.close()


def _connect(storage: StorageConfig | None = None) -> duckdb.DuckDBPyConnection:
    config: dict[str, Any] = {
        "memory_limit": MEMORY_LIMIT,
        "threads": int(DUCKDB_THREADS),
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    }
    if EXTENSION_DIR:
        config["extension_directory"] = EXTENSION_DIR
    conn = duckdb.connect(":memory:", config=config)
    for extension in _S3_EXTENSIONS:
        conn.load_extension(extension)
    if storage is not None:
        _configure_s3(conn, storage)
    return conn


def _configure_s3(conn: duckdb.DuckDBPyConnection, storage: StorageConfig) -> None:
    conn.execute(
        "CREATE OR REPLACE SECRET s3_default ("
        "TYPE s3, "
        f"KEY_ID {sql_literal(storage.access_key)}, "
        f"SECRET {sql_literal(storage.secret_key)}, "
        f"ENDPOINT {sql_literal(storage.endpoint)}, "
        f"REGION {sql_literal(storage.region)}, "
        "URL_STYLE 'path', "
        f"USE_SSL {'true' if storage.use_ssl else 'false'}"
        ")"
    )


def _with_timeout(
    conn: duckdb.DuckDBPyConnection, func: Any, timeout_s: float = DEFAULT_TIMEOUT_S
) -> Any:
    """Run a blocking DuckDB call with a watchdog that interrupts on timeout —
    the only supported cancellation for in-flight DuckDB queries."""
    timer = threading.Timer(timeout_s, conn.interrupt)
    timer.start()
    try:
        return func()
    except duckdb.InterruptException as exc:
        raise Interrupted() from exc
    finally:
        timer.cancel()


# ── Type mapping ────────────────────────────────────────────────────────────────


def _one(row: tuple[Any, ...] | None) -> tuple[Any, ...]:
    if row is None:  # aggregates always yield one row; guard for mypy + safety
        raise InvalidInput("The query returned no result.")
    return row


def _columns_from_description(description: Any) -> list[Column]:
    return [Column(name=col[0], type=str(col[1])) for col in description]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, uuid.UUID | bytes):
        return str(value)
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _rows_as_dicts(cursor: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [col[0] for col in cursor.description]
    return [
        {name: _jsonable(value) for name, value in zip(columns, row, strict=True)}
        for row in cursor.fetchall()
    ]


# ── CSV / Parquet / XLSX inference on an uploaded file ────────────────────────────


def _read_expr(local_path: str, filename: str) -> tuple[str, dict[str, Any]]:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return f"read_csv_auto({sql_literal(local_path)}, sample_size=-1)", {"format": "csv"}
    if lower.endswith(".parquet"):
        return f"read_parquet({sql_literal(local_path)})", {"format": "parquet"}
    if lower.endswith(".xlsx"):
        return (
            f"read_xlsx({sql_literal(local_path)}, all_varchar=false)",
            {"format": "xlsx", "sheet": "first"},
        )
    raise InvalidInput("Unsupported file type — expected .csv, .parquet, or .xlsx.")


def infer_file(local_path: str, filename: str, *, preview_rows: int = 50) -> InferResult:
    read_expr, params = _read_expr(local_path, filename)
    conn = _connect()
    if filename.lower().endswith(".xlsx"):
        conn.load_extension("excel")
    try:
        cursor = _with_timeout(
            conn, lambda: conn.execute(f"SELECT * FROM {read_expr} LIMIT {int(preview_rows)}")
        )
        columns = _columns_from_description(cursor.description)
        preview = _rows_as_dicts(cursor)
    except duckdb.Error as exc:
        raise _map_duck_error(exc) from exc
    finally:
        conn.close()
    if not columns:
        raise InvalidInput("The file has no columns to import.")
    return InferResult(columns=columns, preview=preview, params=params)


def convert_upload_to_parquet(
    local_path: str, filename: str, storage: StorageConfig, dest_key: str
) -> tuple[list[Column], int]:
    """Read the raw upload, write typed parquet to s3://bucket/dest_key. Returns
    (schema, row_count)."""
    read_expr, _ = _read_expr(local_path, filename)
    conn = _connect(storage)
    if filename.lower().endswith(".xlsx"):
        conn.load_extension("excel")
    dest = f"s3://{storage.bucket}/{dest_key}"
    try:
        _with_timeout(
            conn,
            lambda: conn.execute(
                f"COPY (SELECT * FROM {read_expr}) TO {sql_literal(dest)} (FORMAT parquet)"
            ),
        )
        schema_cursor = conn.execute(f"SELECT * FROM {read_expr} LIMIT 0")
        columns = _columns_from_description(schema_cursor.description)
        row_count = _one(
            conn.execute(f"SELECT count(*) FROM read_parquet({sql_literal(dest)})").fetchone()
        )[0]
    except duckdb.Error as exc:
        raise _map_duck_error(exc) from exc
    finally:
        conn.close()
    return columns, int(row_count)


# ── Parquet-backed dataset access (s3) ───────────────────────────────────────────


def sample_parquet(
    storage: StorageConfig, s3_uri: str, *, limit: int
) -> tuple[list[Column], list[dict[str, Any]]]:
    conn = _connect(storage)
    try:
        cursor = _with_timeout(
            conn,
            lambda: conn.execute(
                f"SELECT * FROM read_parquet({sql_literal(s3_uri)}) LIMIT {int(limit)}"
            ),
        )
        return _columns_from_description(cursor.description), _rows_as_dicts(cursor)
    except duckdb.Error as exc:
        raise _map_duck_error(exc) from exc
    finally:
        conn.close()


def profile_parquet(storage: StorageConfig, s3_uri: str) -> dict[str, Any]:
    conn = _connect(storage)
    try:
        return _profile(conn, f"read_parquet({sql_literal(s3_uri)})")
    except duckdb.Error as exc:
        raise _map_duck_error(exc) from exc
    finally:
        conn.close()


def validate_parquet(storage: StorageConfig, s3_uri: str) -> tuple[list[Column], int]:
    """Full read of an uploaded parquet before we trust it as v1 (plan §6)."""
    conn = _connect(storage)
    try:
        columns = _columns_from_description(
            conn.execute(f"SELECT * FROM read_parquet({sql_literal(s3_uri)}) LIMIT 0").description
        )
        row_count = _with_timeout(
            conn,
            lambda: conn.execute(
                f"SELECT count(*) FROM read_parquet({sql_literal(s3_uri)})"
            ).fetchone(),
        )[0]
        return columns, int(row_count)
    except duckdb.Error as exc:
        raise InvalidInput("The parquet file could not be read.") from exc
    finally:
        conn.close()


# ── Profiling (explicit aggregates — never SUMMARIZE, see ADR-0006) ──────────────


def _profile(conn: duckdb.DuckDBPyConnection, relation: str) -> dict[str, Any]:
    columns = _columns_from_description(
        conn.execute(f"SELECT * FROM {relation} LIMIT 0").description
    )
    total = _one(conn.execute(f"SELECT count(*) FROM {relation}").fetchone())[0]
    column_profiles: list[dict[str, Any]] = []
    for col in columns:
        ident = qualified_ident(col.name)
        nulls, distinct = _one(
            conn.execute(
                f"SELECT count(*) - count({ident}), approx_count_distinct({ident}) FROM {relation}"
            ).fetchone()
        )
        entry: dict[str, Any] = {
            "name": col.name,
            "type": col.type,
            "null_count": int(nulls),
            "distinct_approx": int(distinct),
        }
        if _is_numeric(col.type):
            low, high, mean = _one(
                conn.execute(
                    f"SELECT min({ident}), max({ident}), avg({ident}) FROM {relation}"
                ).fetchone()
            )
            entry.update(min=_jsonable(low), max=_jsonable(high), mean=_jsonable(mean))
        elif _is_temporal(col.type):
            low, high = _one(
                conn.execute(f"SELECT min({ident}), max({ident}) FROM {relation}").fetchone()
            )
            entry.update(min=_jsonable(low), max=_jsonable(high))
        else:
            top = conn.execute(
                f"SELECT {ident} AS value, count(*) AS n FROM {relation} "
                f"WHERE {ident} IS NOT NULL GROUP BY 1 ORDER BY n DESC, 1 LIMIT 5"
            ).fetchall()
            entry["top_values"] = [{"value": _jsonable(v), "count": int(n)} for v, n in top]
        column_profiles.append(entry)
    return {"row_count": int(total), "columns": column_profiles}


def _is_numeric(duck_type: str) -> bool:
    t = duck_type.upper()
    return any(
        token in t for token in ("INT", "DECIMAL", "DOUBLE", "FLOAT", "REAL", "NUMERIC", "HUGEINT")
    )


def _is_temporal(duck_type: str) -> bool:
    t = duck_type.upper()
    return any(token in t for token in ("DATE", "TIME", "TIMESTAMP"))


# ── Read-only Postgres attach ────────────────────────────────────────────────────


@dataclass
class PgAttach:
    host: str
    port: int
    database: str
    user: str
    password: str


def _attach_postgres(conn: duckdb.DuckDBPyConnection, target: PgAttach, alias: str) -> None:
    conn.load_extension("postgres")
    conn.execute(
        "CREATE OR REPLACE SECRET pg_src ("
        "TYPE postgres, "
        f"HOST {sql_literal(target.host)}, "
        f"PORT {int(target.port)}, "
        f"DATABASE {sql_literal(target.database)}, "
        f"USER {sql_literal(target.user)}, "
        f"PASSWORD {sql_literal(target.password)}"
        ")"
    )
    # READ_ONLY is mandatory — the modern postgres extension can otherwise write.
    conn.execute(f"ATTACH '' AS {alias} (TYPE postgres, SECRET pg_src, READ_ONLY)")


def inspect_postgres_table(
    target: PgAttach, table: str, *, preview_rows: int = 50
) -> tuple[list[Column], list[dict[str, Any]]]:
    conn = _connect()
    try:
        _attach_postgres(conn, target, "src")
        relation = f"src.{qualified_ident(table)}"
        cursor = _with_timeout(
            conn, lambda: conn.execute(f"SELECT * FROM {relation} LIMIT {int(preview_rows)}")
        )
        return _columns_from_description(cursor.description), _rows_as_dicts(cursor)
    except duckdb.Error as exc:
        raise _map_duck_error(exc) from exc
    finally:
        conn.close()


def sample_postgres_table(
    target: PgAttach, table: str, *, limit: int
) -> tuple[list[Column], list[dict[str, Any]]]:
    return inspect_postgres_table(target, table, preview_rows=limit)


def profile_postgres_table(target: PgAttach, table: str) -> dict[str, Any]:
    conn = _connect()
    try:
        _attach_postgres(conn, target, "src")
        return _profile(conn, f"src.{qualified_ident(table)}")
    except duckdb.Error as exc:
        raise _map_duck_error(exc) from exc
    finally:
        conn.close()


def postgres_table_estimate(target: PgAttach, table: str) -> int | None:
    """Planner estimate (pg_class.reltuples) — exact COUNT(*) over a customer table
    is a Phase 2 job (plan §7)."""
    inner = (
        f"SELECT reltuples::bigint AS n FROM pg_class WHERE oid = to_regclass({sql_literal(table)})"  # noqa: E501
    )
    conn = _connect()
    try:
        _attach_postgres(conn, target, "src")
        row = conn.execute(f"SELECT * FROM postgres_query('src', {sql_literal(inner)})").fetchone()
        if row is None or row[0] is None or int(row[0]) < 0:
            return None
        return int(row[0])
    except duckdb.Error:
        return None  # estimate is best-effort
    finally:
        conn.close()


# ── duckdb_file datasets (a .duckdb database inside project storage, over httpfs) ──


def _attach_duckdb_file(conn: duckdb.DuckDBPyConnection, s3_uri: str, alias: str = "src") -> None:
    # READ_ONLY is mandatory for httpfs attaches and our policy everywhere.
    conn.execute(f"ATTACH {sql_literal(s3_uri)} AS {alias} (READ_ONLY)")


def inspect_duckdb_file(
    storage: StorageConfig, s3_uri: str, table: str, *, preview_rows: int = 50
) -> tuple[list[Column], list[dict[str, Any]]]:
    conn = _connect(storage)
    try:
        _attach_duckdb_file(conn, s3_uri)
        relation = f"src.{qualified_ident(table)}"
        cursor = _with_timeout(
            conn, lambda: conn.execute(f"SELECT * FROM {relation} LIMIT {int(preview_rows)}")
        )
        return _columns_from_description(cursor.description), _rows_as_dicts(cursor)
    except duckdb.Error as exc:
        raise _map_duck_error(exc) from exc
    finally:
        conn.close()


def profile_duckdb_file(storage: StorageConfig, s3_uri: str, table: str) -> dict[str, Any]:
    conn = _connect(storage)
    try:
        _attach_duckdb_file(conn, s3_uri)
        return _profile(conn, f"src.{qualified_ident(table)}")
    except duckdb.Error as exc:
        raise _map_duck_error(exc) from exc
    finally:
        conn.close()


# ── Error mapping ────────────────────────────────────────────────────────────────


def _map_duck_error(exc: duckdb.Error) -> Exception:
    message = str(exc).lower()
    if isinstance(exc, duckdb.InterruptException):
        return Interrupted()
    if "password authentication failed" in message or "authentication" in message:
        return AuthFailed()
    if "does not exist" in message and "database" in message:
        return DatabaseNotFound()
    if any(token in message for token in ("could not connect", "connection refused", "no route")):
        return HostUnreachable()
    if any(token in message for token in ("no such file", "not found", "does not exist")):
        return ObjectNotFound()
    return InvalidInput("The data could not be read.")
