"""Resolve a recipe's inputs to parquet snapshot URIs and run its compiler.

Shared by the preview endpoint (sampled, no write) and the build worker (full, atomic
write). Every input becomes a parquet URI so the engine compiler is uniform and SQL
recipes can execute on a secret-less connection (ADR-0007 §4).

Two phases so the async DB/vault work and the blocking engine snapshots stay cleanly
separated: `plan_inputs` (async) → `materialize_inputs` (sync, run via run_engine).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import Connection, Dataset, DatasetVersion, RecipeInput, Secret
from osaip_api.problem import Problem
from osaip_api.secrets import Vault
from osaip_api.sources import pg_target, s3_config
from osaip_engine import duck
from osaip_engine.recipes import InputSource
from osaip_engine.storage import Storage


@dataclass
class ResolvedInput:
    ordinal: int
    dataset: Dataset
    version: DatasetVersion


@dataclass
class InputPlan:
    """How to get input `ordinal` as parquet: either a direct URI (parquet-backed
    datasets) or an external snapshot spec (postgres table / duckdb file)."""

    ordinal: int
    direct_uri: str | None = None
    external_kind: str | None = None  # "table" | "duckdb_file"
    pg_target: duck.PgAttach | None = None
    duckdb_s3_uri: str | None = None
    table: str | None = None


async def resolve_inputs(session: AsyncSession, recipe_id: uuid.UUID) -> list[ResolvedInput]:
    """Ordered inputs with their current versions; 422 if any input is never-built."""
    rows = (
        await session.execute(
            select(RecipeInput.ordinal, Dataset)
            .join(Dataset, Dataset.id == RecipeInput.dataset_id)
            .where(RecipeInput.recipe_id == recipe_id)
            .order_by(RecipeInput.ordinal)
        )
    ).all()
    resolved: list[ResolvedInput] = []
    for ordinal, dataset in rows:
        if dataset.current_version == 0:
            raise Problem(
                422,
                title="Input not built",
                detail=f"Input dataset {dataset.name!r} has no built version yet.",
                hint="Build the upstream datasets first.",
                slug="input-not-built",
            )
        version = (
            await session.execute(
                select(DatasetVersion).where(
                    DatasetVersion.dataset_id == dataset.id,
                    DatasetVersion.version == dataset.current_version,
                )
            )
        ).scalar_one()
        resolved.append(ResolvedInput(ordinal=ordinal, dataset=dataset, version=version))
    return resolved


async def _connection_secret(
    session: AsyncSession, vault: Vault, connection: Connection
) -> str | None:
    if connection.secret_id is None:
        return None
    secret = (
        await session.execute(select(Secret).where(Secret.id == connection.secret_id))
    ).scalar_one()
    return vault.decrypt(secret.ciphertext)


async def plan_inputs(
    session: AsyncSession, vault: Vault, inputs: list[ResolvedInput]
) -> list[InputPlan]:
    """Async phase: decrypt secrets, resolve connection params. No engine I/O here."""
    plans: list[InputPlan] = []
    for item in inputs:
        dataset = item.dataset
        if dataset.kind in ("file", "s3"):
            plans.append(InputPlan(ordinal=item.ordinal, direct_uri=item.version.location))
            continue
        connection = (
            await session.execute(select(Connection).where(Connection.id == dataset.connection_id))
        ).scalar_one()
        secret = await _connection_secret(session, vault, connection)
        if dataset.kind == "table":
            plans.append(
                InputPlan(
                    ordinal=item.ordinal,
                    external_kind="table",
                    pg_target=pg_target(connection, secret),
                    table=dataset.params["table"],
                )
            )
        else:  # duckdb_file
            _ = s3_config  # duckdb files live on the platform bucket; storage config used
            plans.append(
                InputPlan(
                    ordinal=item.ordinal,
                    external_kind="duckdb_file",
                    duckdb_s3_uri=dataset.params["path"],
                    table=dataset.params["table"],
                )
            )
    return plans


def materialize_inputs(
    storage: Storage, plans: list[InputPlan], snapshot_prefix: str, *, limit: int | None
) -> list[InputSource]:
    """Sync phase (run via run_engine): direct URIs pass through; external inputs are
    snapshotted to parquet — sampled when `limit` is set (preview), whole otherwise."""
    sources: list[InputSource] = []
    for plan in plans:
        if plan.direct_uri is not None:
            sources.append(InputSource(plan.ordinal, plan.direct_uri))
            continue
        dest_key = f"{snapshot_prefix}/in_{plan.ordinal + 1}.parquet"
        if plan.external_kind == "table":
            assert plan.pg_target is not None and plan.table is not None
            duck.snapshot_postgres_to_parquet(
                plan.pg_target, plan.table, storage.config, dest_key, limit=limit
            )
        else:
            assert plan.duckdb_s3_uri is not None and plan.table is not None
            duck.snapshot_duckdb_file_to_parquet(
                storage.config, plan.duckdb_s3_uri, plan.table, dest_key, limit=limit
            )
        sources.append(InputSource(plan.ordinal, f"s3://{storage.config.bucket}/{dest_key}"))
    return sources


def make_snapshot_prefix(project_key: str, token: str) -> str:
    return f"projects/{project_key}/artifacts/snapshots/{token}"


def compile_and_execute_preview(
    con: Any, kind: str, config: dict[str, Any], sources: list[InputSource], *, limit: int
) -> dict[str, Any]:
    """Compile the recipe and return {columns, rows} for the first output, capped at
    `limit`. Pure engine work — call via run_engine."""
    from osaip_engine import recipes

    if kind == "split":
        table, _rest = recipes.compile_split(con, config, sources)
    else:
        table = recipes.compile_recipe(con, kind, config, sources)
    frame = con.execute(table.head(limit))
    columns = [{"name": c, "type": str(frame[c].dtype), "nullable": True} for c in frame.columns]
    return {"columns": columns, "rows": _jsonable_records(frame), "limit": limit}


def _jsonable_records(frame: Any) -> list[dict[str, Any]]:
    import math

    records: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        clean: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                clean[key] = None  # non-finite floats aren't valid JSON (plan §3)
            elif hasattr(value, "isoformat"):
                clean[key] = value.isoformat()
            elif isinstance(value, bool | int | float | str) or value is None:
                clean[key] = value
            else:
                clean[key] = str(value)
        records.append(clean)
    return records
