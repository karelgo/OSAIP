"""Flow view-model (spec §3.2): the project's dataset/recipe DAG plus a per-dataset
freshness status, for the graph canvas. Read-only, ETagged (§6.6).

Staleness contract (ADR-0007 §2): a produced dataset is stale iff its producer's
`config_hash` differs from the built version's `recipe_config_hash`, OR any input's
`current_version` is newer than the version this build consumed. `input_versions` is
keyed by the input DATASET ID rendered as a string (`str(dataset_id)`) — the same key
the worker writes at build time.
"""

import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.etag import etag_json_response
from osaip_api.models import Dataset, DatasetVersion, Job, JobStep, Recipe
from osaip_api.permissions import load_project_context
from osaip_api.recipes_service import compute_staleness, load_graph
from osaip_api.schemas import FlowOut

router = APIRouter(prefix="/projects/{key}/flow", tags=["flow"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

_FINISHED = ("succeeded", "failed", "skipped")


def _base_status(
    dataset: Dataset,
    *,
    produced: bool,
    version: DatasetVersion | None,
    producer_hash: str | None,
    input_datasets: list[Dataset],
) -> str:
    if not produced:
        # A registered-but-unbuilt source shouldn't happen for P1 datasets, but be safe.
        return "source_empty" if dataset.current_version == 0 else "source"
    # Shared staleness contract (recipes_service.compute_staleness) — the same predicate
    # build resolution uses, so the Flow and the build planner never disagree.
    return compute_staleness(
        current_version=dataset.current_version,
        version=version,
        producer_hash=producer_hash,
        input_datasets=input_datasets,
    )


@router.get("", response_model=FlowOut)
async def get_flow(key: str, request: Request, user: CurrentUser, session: DbSession) -> Response:
    ctx = await load_project_context(session, user, key, min_role="viewer")

    datasets = (
        (
            await session.execute(
                select(Dataset)
                .where(Dataset.project_id == ctx.project.id, Dataset.status == "active")
                .order_by(Dataset.name)
            )
        )
        .scalars()
        .all()
    )
    recipes = (
        (
            await session.execute(
                select(Recipe)
                .where(Recipe.project_id == ctx.project.id, Recipe.status == "active")
                .order_by(Recipe.name)
            )
        )
        .scalars()
        .all()
    )
    graph = await load_graph(session, ctx.project.id)
    datasets_by_id = {dataset.id: dataset for dataset in datasets}
    id_to_name = {dataset.id: dataset.name for dataset in datasets}
    recipes_by_id = {recipe.id: recipe for recipe in recipes}

    # Current DatasetVersion per dataset (version == current_version) in one pass.
    current_versions: dict[Any, DatasetVersion] = {}
    for dataset_version in (
        (
            await session.execute(
                select(DatasetVersion)
                .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
                .where(
                    Dataset.project_id == ctx.project.id,
                    DatasetVersion.version == Dataset.current_version,
                )
            )
        )
        .scalars()
        .all()
    ):
        current_versions[dataset_version.dataset_id] = dataset_version

    # Latest step per target dataset (build/failed overlay). One query, latest wins.
    running: set[Any] = set()
    latest_finished: dict[Any, tuple[datetime.datetime, str]] = {}
    for target_id, status, finished_at in (
        await session.execute(
            select(JobStep.target_dataset_id, JobStep.status, JobStep.finished_at)
            .join(Job, Job.id == JobStep.job_id)
            .where(Job.project_id == ctx.project.id, JobStep.target_dataset_id.isnot(None))
        )
    ).all():
        if status == "running":
            running.add(target_id)
        if status in _FINISHED and finished_at is not None:
            seen = latest_finished.get(target_id)
            if seen is None or finished_at > seen[0]:
                latest_finished[target_id] = (finished_at, status)

    dataset_vms = []
    for dataset in datasets:
        producer_id = graph.producer.get(dataset.id)
        produced = producer_id is not None
        producer = recipes_by_id.get(producer_id) if producer_id is not None else None
        input_datasets = [
            datasets_by_id[input_id]
            for input_id in (graph.inputs.get(producer_id, []) if producer_id is not None else [])
            if input_id in datasets_by_id
        ]
        version = current_versions.get(dataset.id)
        status = _base_status(
            dataset,
            produced=produced,
            version=version,
            producer_hash=producer.config_hash if producer is not None else None,
            input_datasets=input_datasets,
        )
        if dataset.id in running:
            status = "building"
        elif dataset.id in latest_finished and latest_finished[dataset.id][1] == "failed":
            status = "failed"
        dataset_vms.append(
            {
                "name": dataset.name,
                "kind": dataset.kind,
                "status": status,
                "classification": dataset.classification,
                "bbn_level": dataset.bbn_level,
                "confidentiality": dataset.confidentiality,
                "current_version": dataset.current_version,
                "row_count": version.row_count if version is not None else None,
            }
        )

    recipe_vms = []
    edges = []
    for recipe in recipes:
        input_names = [
            id_to_name[input_id]
            for input_id in graph.inputs.get(recipe.id, [])
            if input_id in id_to_name
        ]
        output_names = [
            id_to_name[output_id]
            for output_id in graph.outputs.get(recipe.id, [])
            if output_id in id_to_name
        ]
        recipe_node = f"recipe:{recipe.id}"
        recipe_vms.append(
            {
                "id": str(recipe.id),
                "name": recipe.name,
                "kind": recipe.kind,
                "input_datasets": input_names,
                "output_datasets": output_names,
            }
        )
        for input_name in input_names:
            edges.append({"from": f"dataset:{input_name}", "to": recipe_node})
        for output_name in output_names:
            edges.append({"from": recipe_node, "to": f"dataset:{output_name}"})

    payload = {
        "datasets": dataset_vms,
        "recipes": recipe_vms,
        "edges": edges,
        "capabilities": {"can_edit": ctx.capabilities["can_edit"]},
    }
    return etag_json_response(request, payload)
