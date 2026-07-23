"""Datasets: registration (from upload or connection source), list/detail, sample,
profile, labels (CP-1) and purpose metadata (CP-2). Phase 1 plan §7-§8.

Mutation ordering everywhere: mutate → publish_event → write_audit LAST → commit
(ADR-0005 advisory-lock contract).
"""

import base64
import json
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.events import publish_event
from osaip_api.models import Connection, Dataset, DatasetVersion, Secret
from osaip_api.object_refs import remove_object_ref, upsert_object_ref
from osaip_api.permissions import ProjectContext, load_project_context
from osaip_api.problem import Problem
from osaip_api.schemas import (
    DatasetListOut,
    DatasetOut,
    ProfileOut,
    SampleOut,
)
from osaip_api.secrets import Vault
from osaip_api.sources import (
    contained_duckdb_uri,
    engine_problem,
    pg_target,
    s3_config,
    validate_rel_path,
    validate_table_name,
)
from osaip_engine import duck
from osaip_engine.aio import run_engine
from osaip_engine.errors import EngineError, InvalidInput
from osaip_engine.storage import Storage
from osaip_shared.ids import new_id
from osaip_shared.storage_layout import dataset_version_location, upload_prefix

router = APIRouter(prefix="/projects/{key}/datasets", tags=["datasets"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
CLASSIFICATIONS = ("none", "persoonsgegevens", "bijzonder", "bsn")
BBN_LEVELS = ("bbn1", "bbn2", "bbn3")
CONFIDENTIALITY = ("intern", "vertrouwelijk", "geheim")


class SourceIn(BaseModel):
    kind: Literal["upload", "table", "s3", "duckdb_file"]
    upload_id: str | None = None
    connection_id: str | None = None
    table: str | None = None
    path: str | None = None


class DatasetCreate(BaseModel):
    name: str = Field(pattern=_NAME_RE.pattern)
    source: SourceIn
    description: str = Field(default="", max_length=10_000)
    classification: Literal["none", "persoonsgegevens", "bijzonder", "bsn"] = "none"
    bbn_level: Literal["bbn1", "bbn2", "bbn3"] | None = None
    confidentiality: Literal["intern", "vertrouwelijk", "geheim"] | None = None
    # CP-2: required unless inherited from the source connection
    legal_basis: str | None = Field(default=None, max_length=500)
    purpose_codes: list[str] | None = Field(default=None, max_length=20)


class DatasetPatch(BaseModel):
    description: str | None = Field(default=None, max_length=10_000)
    classification: Literal["none", "persoonsgegevens", "bijzonder", "bsn"] | None = None
    bbn_level: Literal["bbn1", "bbn2", "bbn3"] | None = None
    confidentiality: Literal["intern", "vertrouwelijk", "geheim"] | None = None
    legal_basis: str | None = Field(default=None, min_length=1, max_length=500)
    purpose_codes: list[str] | None = Field(default=None, min_length=1, max_length=20)
    # CP-1 per-column labels: {column_name: classification}
    column_classifications: dict[str, str] | None = None


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _columns_payload(version: DatasetVersion | None) -> list[dict[str, Any]]:
    if version is None:
        return []
    return list(version.schema_json.get("columns", []))


def _payload(dataset: Dataset, version: DatasetVersion | None) -> dict[str, Any]:
    return {
        "name": dataset.name,
        "kind": dataset.kind,
        "description": dataset.description,
        "status": dataset.status,
        "classification": dataset.classification,
        "bbn_level": dataset.bbn_level,
        "confidentiality": dataset.confidentiality,
        "legal_basis": dataset.legal_basis,
        "purpose_codes": dataset.purpose_codes,
        "params": dataset.params,
        "connection_id": str(dataset.connection_id) if dataset.connection_id else None,
        "current_version": dataset.current_version,
        "columns": _columns_payload(version),
        "row_count": version.row_count if version else None,
        "row_count_kind": version.row_count_kind if version else None,
        "has_profile": bool(version and version.profile_json),
        "created_at": dataset.created_at.isoformat(),
        "updated_at": dataset.updated_at.isoformat(),
    }


def _list_item(dataset: Dataset, version: DatasetVersion | None) -> dict[str, Any]:
    return {
        "name": dataset.name,
        "kind": dataset.kind,
        "description": dataset.description,
        "classification": dataset.classification,
        "bbn_level": dataset.bbn_level,
        "confidentiality": dataset.confidentiality,
        "row_count": version.row_count if version else None,
        "row_count_kind": version.row_count_kind if version else None,
        "current_version": dataset.current_version,
        "updated_at": dataset.updated_at.isoformat(),
    }


async def _get_dataset(session: AsyncSession, ctx: ProjectContext, name: str) -> Dataset:
    dataset = (
        await session.execute(
            select(Dataset).where(
                Dataset.project_id == ctx.project.id,
                Dataset.name == name,
                Dataset.status == "active",
            )
        )
    ).scalar_one_or_none()
    if dataset is None:
        raise Problem(
            404,
            title="Dataset not found",
            detail=f"No dataset {name!r} in this project.",
            hint="Check the dataset name.",
            slug="not-found",
        )
    return dataset


async def _current_version(session: AsyncSession, dataset: Dataset) -> DatasetVersion | None:
    if dataset.current_version == 0:
        return None
    return (
        await session.execute(
            select(DatasetVersion).where(
                DatasetVersion.dataset_id == dataset.id,
                DatasetVersion.version == dataset.current_version,
            )
        )
    ).scalar_one_or_none()


async def _get_connection(
    session: AsyncSession, ctx: ProjectContext, connection_id: str
) -> Connection:
    connection = (
        await session.execute(
            select(Connection).where(
                Connection.id == connection_id,
                Connection.project_id == ctx.project.id,
                Connection.status == "active",
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise Problem(
            404,
            title="Connection not found",
            detail="No such active connection in this project.",
            hint="Check the connection id.",
            slug="not-found",
        )
    return connection


async def _connection_secret(
    session: AsyncSession, vault: Vault, connection: Connection
) -> str | None:
    if connection.secret_id is None:
        return None
    secret = (
        await session.execute(select(Secret).where(Secret.id == connection.secret_id))
    ).scalar_one()
    return vault.decrypt(secret.ciphertext)


def _schema_json(columns: list[duck.Column]) -> dict[str, Any]:
    return {
        "columns": [
            {"name": col.name, "type": col.type, "nullable": col.nullable, "classification": "none"}
            for col in columns
        ]
    }


# ── Create (from upload OR connection source) ────────────────────────────────────


@router.post("", status_code=201, response_model=DatasetOut)
async def create_dataset(
    key: str, body: DatasetCreate, request: Request, user: CurrentUser, session: DbSession
) -> Any:
    ctx = await load_project_context(session, user, key, min_role="editor")
    storage: Storage = request.app.state.storage
    vault: Vault = request.app.state.vault

    duplicate = (
        await session.execute(
            select(Dataset).where(Dataset.project_id == ctx.project.id, Dataset.name == body.name)
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise Problem(
            409,
            title="Name already in use",
            detail=f"A dataset named {body.name!r} already exists in this project.",
            hint="Pick a different name (archived datasets keep their name).",
            slug="conflict",
        )

    source = body.source
    connection: Connection | None = None
    legal_basis = body.legal_basis
    purpose_codes = body.purpose_codes

    if source.kind == "upload":
        if not source.upload_id:
            raise Problem(
                422,
                title="Missing upload_id",
                detail="source.upload_id is required.",
                hint="Upload a file first, then confirm it.",
                slug="validation",
            )
        dataset_kind = "file"
    else:
        if not source.connection_id:
            raise Problem(
                422,
                title="Missing connection_id",
                detail="source.connection_id is required for this source kind.",
                hint="Pick a connection.",
                slug="validation",
            )
        connection = await _get_connection(session, ctx, source.connection_id)
        expected = {"table": "postgres", "s3": "s3", "duckdb_file": "duckdb_file"}[source.kind]
        if connection.kind != expected:
            raise Problem(
                422,
                title="Connection kind mismatch",
                detail=f"Source {source.kind!r} needs a {expected} connection; "
                f"{connection.name!r} is {connection.kind}.",
                hint="Pick a matching connection.",
                slug="validation",
            )
        # CP-2 inheritance: connection metadata is the default
        legal_basis = legal_basis or connection.legal_basis
        purpose_codes = purpose_codes or connection.purpose_codes
        dataset_kind = {"table": "table", "s3": "s3", "duckdb_file": "duckdb_file"}[source.kind]

    if not legal_basis or not purpose_codes:
        raise Problem(
            422,
            title="Purpose metadata required",
            detail="legal_basis and purpose_codes are required (CP-2).",
            hint="State the legal basis and at least one purpose code for this dataset.",
            slug="validation",
        )

    params: dict[str, Any] = {}
    profile_json: dict[str, Any] | None = None
    row_count_kind: str | None = None
    row_count: int | None = None

    try:
        if source.kind == "upload":
            prefix = upload_prefix(ctx.project.key, source.upload_id or "")
            meta_bytes = await run_engine(lambda: storage.get_bytes(f"{prefix}/meta.json"))
            meta = json.loads(meta_bytes)
            params = dict(meta.get("params", {}))
            raw_uri = f"s3://{storage.config.bucket}/{prefix}/{meta['filename']}"
            dest_key = dataset_version_location(ctx.project.key, body.name, 1)
            if meta["format"] == "parquet":
                # validating full read before we trust attacker-supplied parquet
                await run_engine(lambda: duck.validate_parquet(storage.config, raw_uri))
            columns, count = await run_engine(
                lambda: duck.convert_upload_to_parquet(
                    raw_uri, meta["filename"], storage.config, dest_key
                )
            )
            location = f"s3://{storage.config.bucket}/{dest_key}"
            fmt = "parquet"
            row_count, row_count_kind = count, "exact"
            profile_json = await run_engine(lambda: duck.profile_parquet(storage.config, location))
        elif source.kind == "table":
            table = validate_table_name(source.table or "")
            secret = await _connection_secret(session, vault, connection)  # type: ignore[arg-type]
            target = pg_target(connection, secret)  # type: ignore[arg-type]
            columns, _ = await run_engine(
                lambda: duck.inspect_postgres_table(target, table, preview_rows=0)
            )
            row_count = await run_engine(lambda: duck.postgres_table_estimate(target, table))
            row_count_kind = "estimate" if row_count is not None else None
            params = {"table": table}
            location = f"postgres:{table}"
            fmt = "external"
        elif source.kind == "s3":
            rel_path = validate_rel_path(source.path or "", suffix=".parquet")
            secret = await _connection_secret(session, vault, connection)  # type: ignore[arg-type]
            config = s3_config(connection, secret)  # type: ignore[arg-type]
            location = f"s3://{config.bucket}/{rel_path}"
            columns, count = await run_engine(lambda: duck.validate_parquet(config, location))
            row_count, row_count_kind = count, "exact"
            params = {"path": rel_path}
            fmt = "external"
        else:  # duckdb_file
            table = validate_table_name(source.table or "")
            uri = contained_duckdb_uri(
                storage.config.bucket,
                ctx.project.key,
                str(connection.config["path"]),  # type: ignore[union-attr]
            )
            columns, _ = await run_engine(
                lambda: duck.inspect_duckdb_file(storage.config, uri, table, preview_rows=0)
            )
            params = {"table": table, "path": uri}
            location = f"{uri}#{table}"
            fmt = "external"
    except InvalidInput as exc:
        raise Problem(
            422,
            title="Source could not be read",
            detail=exc.public_message,
            hint="Check the source file/table and try again.",
            slug="validation",
        ) from exc
    except EngineError as exc:
        raise engine_problem(exc) from exc

    dataset = Dataset(
        id=new_id(),
        project_id=ctx.project.id,
        name=body.name,
        kind=dataset_kind,
        connection_id=connection.id if connection else None,
        description=body.description,
        classification=body.classification,
        bbn_level=body.bbn_level,
        confidentiality=body.confidentiality,
        legal_basis=legal_basis,
        purpose_codes=purpose_codes,
        params=params,
        current_version=1,
        created_by=user.id,
    )
    session.add(dataset)
    await session.flush()
    session.add(
        DatasetVersion(
            id=new_id(),
            dataset_id=dataset.id,
            version=1,
            location=location,
            format=fmt,
            schema_json=_schema_json(columns),
            row_count=row_count,
            row_count_kind=row_count_kind,
            profile_json=profile_json,
        )
    )
    await upsert_object_ref(
        session,
        kind="dataset",
        project_id=ctx.project.id,
        name=body.name,
        description=body.description,
        url_path=f"/p/{ctx.project.key}/datasets/{body.name}",
    )
    await publish_event(
        session,
        topic="datasets",
        type="dataset.created",
        project_id=ctx.project.id,
        payload={"name": body.name},
    )
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="dataset.created",
        object_kind="dataset",
        object_id=body.name,
        details={"kind": dataset_kind, "source": source.kind},
        ip=_client_ip(request),
    )
    await session.commit()
    version = await _current_version(session, dataset)
    return _payload(dataset, version)


# ── Read ─────────────────────────────────────────────────────────────────────────


def _encode_cursor(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode()


def _decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor.encode()).decode()
    except Exception as exc:
        raise Problem(
            400,
            title="Invalid cursor",
            detail="The pagination cursor is not valid.",
            hint="Restart from the first page (omit `cursor`).",
            slug="invalid-cursor",
        ) from exc


@router.get("", response_model=DatasetListOut)
async def list_datasets(
    key: str,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    limit: int = 50,
    cursor: str | None = None,
) -> Response:
    from osaip_api.etag import etag_json_response

    ctx = await load_project_context(session, user, key, min_role="viewer")
    limit = max(1, min(limit, 200))
    query = (
        select(Dataset)
        .where(Dataset.project_id == ctx.project.id, Dataset.status == "active")
        .order_by(Dataset.name)
        .limit(limit + 1)
    )
    if cursor:
        query = query.where(Dataset.name > _decode_cursor(cursor))
    datasets = (await session.execute(query)).scalars().all()
    has_more = len(datasets) > limit
    datasets = datasets[:limit]
    items = []
    for dataset in datasets:
        version = await _current_version(session, dataset)
        items.append(_list_item(dataset, version))
    payload = {
        "items": items,
        "next_cursor": _encode_cursor(datasets[-1].name) if has_more and datasets else None,
    }
    return etag_json_response(request, payload)


@router.get("/{name}", response_model=DatasetOut)
async def get_dataset(key: str, name: str, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    dataset = await _get_dataset(session, ctx, name)
    return _payload(dataset, await _current_version(session, dataset))


# ── Mutations ────────────────────────────────────────────────────────────────────


@router.patch("/{name}", response_model=DatasetOut)
async def patch_dataset(
    key: str,
    name: str,
    body: DatasetPatch,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="editor")
    dataset = await _get_dataset(session, ctx, name)
    version = await _current_version(session, dataset)
    changed: list[str] = []
    for field in (
        "description",
        "classification",
        "bbn_level",
        "confidentiality",
        "legal_basis",
        "purpose_codes",
    ):
        value = getattr(body, field)
        if value is not None and value != getattr(dataset, field):
            setattr(dataset, field, value)
            changed.append(field)
    if body.column_classifications:
        if version is None:
            raise Problem(
                422,
                title="No schema yet",
                detail="This dataset has no version to label.",
                hint="Build the dataset first.",
                slug="validation",
            )
        invalid = set(body.column_classifications.values()) - set(CLASSIFICATIONS)
        if invalid:
            raise Problem(
                422,
                title="Invalid classification",
                detail=f"Unknown classification value(s): {sorted(invalid)}.",
                hint=f"Use one of {CLASSIFICATIONS}.",
                slug="validation",
            )
        columns = list(version.schema_json.get("columns", []))
        known = {col["name"] for col in columns}
        unknown = set(body.column_classifications) - known
        if unknown:
            raise Problem(
                422,
                title="Unknown column",
                detail=f"No such column(s): {sorted(unknown)}.",
                hint="Label only existing columns.",
                slug="validation",
            )
        for col in columns:
            if col["name"] in body.column_classifications:
                col["classification"] = body.column_classifications[col["name"]]
        version.schema_json = {**version.schema_json, "columns": columns}
        changed.append("column_classifications")

    if changed:
        if "description" in changed:
            await upsert_object_ref(
                session,
                kind="dataset",
                project_id=ctx.project.id,
                name=dataset.name,
                description=dataset.description,
                url_path=f"/p/{ctx.project.key}/datasets/{dataset.name}",
            )
        await publish_event(
            session,
            topic="datasets",
            type="dataset.updated",
            project_id=ctx.project.id,
            payload={"name": dataset.name},
        )
        await write_audit(
            session,
            actor_id=user.id,
            project_id=ctx.project.id,
            action="dataset.updated",
            object_kind="dataset",
            object_id=dataset.name,
            details={"changed": changed},
            ip=_client_ip(request),
        )
    await session.commit()
    await session.refresh(dataset)
    return _payload(dataset, version)


@router.delete("/{name}", response_model=DatasetOut)
async def archive_dataset(
    key: str, name: str, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="editor")
    dataset = await _get_dataset(session, ctx, name)
    dataset.status = "archived"
    await remove_object_ref(session, kind="dataset", project_id=ctx.project.id, name=dataset.name)
    await publish_event(
        session,
        topic="datasets",
        type="dataset.archived",
        project_id=ctx.project.id,
        payload={"name": dataset.name},
    )
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="dataset.archived",
        object_kind="dataset",
        object_id=dataset.name,
        details={},
        ip=_client_ip(request),
    )
    await session.commit()
    # updated_at is server-side onupdate → expired after the UPDATE; refresh async
    # (plain attribute access would raise MissingGreenlet under asyncpg).
    await session.refresh(dataset)
    return _payload(dataset, await _current_version(session, dataset))


# ── Sample & profile ─────────────────────────────────────────────────────────────


async def _engine_context(
    session: AsyncSession, request: Request, ctx: ProjectContext, dataset: Dataset
) -> tuple[Any, ...]:
    """Resolve what the engine needs for this dataset kind."""
    storage: Storage = request.app.state.storage
    vault: Vault = request.app.state.vault
    version = await _current_version(session, dataset)
    if version is None:
        raise Problem(
            422,
            title="No data yet",
            detail="This dataset has no built version.",
            hint="Build the dataset first.",
            slug="validation",
        )
    if dataset.kind == "file":
        return ("parquet", storage.config, version)
    connection = (
        await session.execute(select(Connection).where(Connection.id == dataset.connection_id))
    ).scalar_one()
    secret = await _connection_secret(session, vault, connection)
    if dataset.kind == "table":
        return ("table", pg_target(connection, secret), version)
    if dataset.kind == "s3":
        return ("s3", s3_config(connection, secret), version)
    return ("duckdb_file", storage.config, version)


@router.get("/{name}/sample", response_model=SampleOut)
async def sample_dataset(
    key: str,
    name: str,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    limit: int = 100,
) -> Response:
    from fastapi.responses import JSONResponse

    ctx = await load_project_context(session, user, key, min_role="viewer")
    dataset = await _get_dataset(session, ctx, name)
    limit = max(1, min(limit, 1000))

    kind, target, version = await _engine_context(session, request, ctx, dataset)

    # Parquet-backed versions are immutable by layout → computed ETag checked BEFORE
    # any engine work (plan §8): a 304 costs zero DuckDB/S3.
    etag: str | None = None
    if kind == "parquet":
        etag = f'W/"{dataset.id}:v{version.version}:{limit}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})

    try:
        if kind == "parquet":
            columns, rows = await run_engine(
                lambda: duck.sample_parquet(target, version.location, limit=limit)
            )
        elif kind == "table":
            columns, rows = await run_engine(
                lambda: duck.sample_postgres_table(target, dataset.params["table"], limit=limit)
            )
        elif kind == "s3":
            columns, rows = await run_engine(
                lambda: duck.sample_parquet(target, version.location, limit=limit)
            )
        else:
            columns, rows = await run_engine(
                lambda: duck.inspect_duckdb_file(
                    target, dataset.params["path"], dataset.params["table"], preview_rows=limit
                )
            )
    except EngineError as exc:
        raise engine_problem(exc) from exc

    schema_cols = {c["name"]: c for c in _columns_payload(version)}
    payload = {
        "columns": [
            {
                "name": col.name,
                "type": col.type,
                "nullable": col.nullable,
                "classification": schema_cols.get(col.name, {}).get("classification", "none"),
            }
            for col in columns
        ],
        "rows": rows,
        "limit": limit,
    }
    response = JSONResponse(content=payload)
    if etag:
        response.headers["ETag"] = etag
    else:
        # external sources mutate without a version bump — never cache (plan §8)
        response.headers["Cache-Control"] = "no-cache"
    return response


@router.get("/{name}/profile", response_model=ProfileOut)
async def get_profile(key: str, name: str, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    """Stored profile, readable by every project member (the POST recompute stays
    editor-only). Added for the Profile tab: reading must never require a write."""
    ctx = await load_project_context(session, user, key, min_role="viewer")
    dataset = await _get_dataset(session, ctx, name)
    version = await _current_version(session, dataset)
    if version is None or not version.profile_json:
        raise Problem(
            404,
            title="No profile yet",
            detail="This dataset has no stored profile.",
            hint="A project editor can compute one from the Profile tab.",
            slug="not-found",
        )
    return {"profile": version.profile_json}


@router.post("/{name}/profile", response_model=ProfileOut)
async def recompute_profile(
    key: str, name: str, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="editor")
    dataset = await _get_dataset(session, ctx, name)
    kind, target, version = await _engine_context(session, request, ctx, dataset)
    try:
        if kind in ("parquet", "s3"):
            profile = await run_engine(lambda: duck.profile_parquet(target, version.location))
        elif kind == "table":
            profile = await run_engine(
                lambda: duck.profile_postgres_table(target, dataset.params["table"])
            )
        else:
            profile = await run_engine(
                lambda: duck.profile_duckdb_file(
                    target, dataset.params["path"], dataset.params["table"]
                )
            )
    except EngineError as exc:
        raise engine_problem(exc) from exc

    version.profile_json = profile
    if kind in ("parquet", "s3"):
        version.row_count = int(profile["row_count"])
        version.row_count_kind = "exact"
    await publish_event(
        session,
        topic="datasets",
        type="dataset.profiled",
        project_id=ctx.project.id,
        payload={"name": dataset.name},
    )
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="dataset.profiled",
        object_kind="dataset",
        object_id=dataset.name,
        details={},
        ip=_client_ip(request),
    )
    await session.commit()
    return {"profile": profile}
