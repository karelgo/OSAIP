"""Build resolution (ADR-0007 §1/§2, spec §3.2): given target datasets, walk the
upstream recipe DAG and produce the topologically ordered list of recipe steps needed
to bring the targets up to date.

A recipe becomes a step iff `force`, OR its output is stale/never-built, OR any upstream
recipe in the closure is itself a step (a rebuilt input makes the downstream stale —
the AC-2 "rebuild only the affected subset" semantics). Only recipes with produced
outputs are steps; pure source datasets are never steps.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import Dataset, DatasetVersion, Project, Recipe
from osaip_api.problem import Problem
from osaip_api.recipes_service import RecipeGraph, compute_staleness, load_graph


@dataclass
class BuildStep:
    recipe_id: uuid.UUID
    target_dataset_id: uuid.UUID  # the recipe's primary output (ordinal 0)
    ordinal: int


async def _resolve_targets(
    session: AsyncSession, project: Project, names: list[str]
) -> list[Dataset]:
    """Active target datasets in the exact order requested (404 if any is missing)."""
    rows = (
        (
            await session.execute(
                select(Dataset).where(
                    Dataset.project_id == project.id,
                    Dataset.name.in_(names),
                    Dataset.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    by_name = {dataset.name: dataset for dataset in rows}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise Problem(
            404,
            title="Target dataset not found",
            detail=f"No active dataset(s) named {sorted(missing)} in this project.",
            hint="Check the target dataset names.",
            slug="not-found",
        )
    return [by_name[name] for name in names]


def _upstream_closure(graph: RecipeGraph, producer_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Every recipe transitively upstream of (and including) each target's producer."""
    closure: set[uuid.UUID] = set()
    stack = list(producer_ids)
    while stack:
        recipe_id = stack.pop()
        if recipe_id in closure:
            continue
        closure.add(recipe_id)
        for input_dataset_id in graph.inputs.get(recipe_id, []):
            upstream = graph.producer.get(input_dataset_id)
            if upstream is not None:
                stack.append(upstream)
    return closure


def _topo_order(closure: set[uuid.UUID], graph: RecipeGraph) -> list[uuid.UUID]:
    """Kahn's algorithm over the recipe subgraph: a recipe follows every recipe that
    produces one of its inputs. Ties are broken by recipe id for a stable order."""
    deps: dict[uuid.UUID, set[uuid.UUID]] = {recipe_id: set() for recipe_id in closure}
    for recipe_id in closure:
        for input_dataset_id in graph.inputs.get(recipe_id, []):
            upstream = graph.producer.get(input_dataset_id)
            if upstream is not None and upstream in closure:
                deps[recipe_id].add(upstream)
    ordered: list[uuid.UUID] = []
    while deps:
        ready = sorted((r for r, d in deps.items() if not d), key=str)
        if not ready:
            # Unreachable: recipe save rejects cycles (recipes_service.would_create_cycle).
            raise Problem(
                422,
                title="Cyclic build graph",
                detail="The recipes upstream of these targets form a cycle.",
                hint="Break the cycle in the flow graph and retry.",
                slug="cycle",
            )
        for recipe_id in ready:
            ordered.append(recipe_id)
            del deps[recipe_id]
        for remaining in deps.values():
            remaining.difference_update(ready)
    return ordered


async def resolve_build(
    session: AsyncSession, project: Project, target_dataset_names: list[str], force: bool
) -> list[BuildStep]:
    """Topologically ordered steps (inputs before outputs) needed to (re)build the
    targets. Empty when everything is already fresh and `force` is false."""
    targets = await _resolve_targets(session, project, target_dataset_names)
    graph = await load_graph(session, project.id)

    unproduced = [target.name for target in targets if target.id not in graph.producer]
    if unproduced:
        raise Problem(
            422,
            title="Nothing to build",
            detail=f"Dataset(s) {sorted(unproduced)} are not produced by any recipe.",
            hint="Only recipe outputs can be built; source datasets are uploaded/registered.",
            slug="not-produced",
        )

    closure = _upstream_closure(graph, [graph.producer[target.id] for target in targets])
    ordered = _topo_order(closure, graph)

    # Preload the datasets + recipes + current versions referenced by the closure so
    # staleness needs no per-recipe round-trips.
    datasets_by_id = {
        dataset.id: dataset
        for dataset in (
            (
                await session.execute(
                    select(Dataset).where(
                        Dataset.project_id == project.id, Dataset.status == "active"
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    recipes_by_id = {
        recipe.id: recipe
        for recipe in (
            (await session.execute(select(Recipe).where(Recipe.id.in_(closure)))).scalars().all()
        )
    }
    current_versions: dict[uuid.UUID, DatasetVersion] = {}
    for version in (
        (
            await session.execute(
                select(DatasetVersion)
                .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
                .where(
                    Dataset.project_id == project.id,
                    DatasetVersion.version == Dataset.current_version,
                )
            )
        )
        .scalars()
        .all()
    ):
        current_versions[version.dataset_id] = version

    def _output_stale(recipe_id: uuid.UUID) -> bool:
        # Only the primary output is built for now (split's `rest` is deferred, §5), so
        # staleness is evaluated on the primary output alone.
        primary = graph.outputs[recipe_id][0]
        output = datasets_by_id.get(primary)
        if output is None:
            return True
        input_datasets = [
            datasets_by_id[input_id]
            for input_id in graph.inputs.get(recipe_id, [])
            if input_id in datasets_by_id
        ]
        status = compute_staleness(
            current_version=output.current_version,
            version=current_versions.get(primary),
            producer_hash=recipes_by_id[recipe_id].config_hash,
            input_datasets=input_datasets,
        )
        return status != "fresh"

    included: set[uuid.UUID] = set()
    steps: list[BuildStep] = []
    for recipe_id in ordered:
        outputs = graph.outputs.get(recipe_id, [])
        if not outputs:
            continue
        include = force or _output_stale(recipe_id)
        if not include:
            include = any(
                graph.producer.get(input_id) in included
                for input_id in graph.inputs.get(recipe_id, [])
            )
        if include:
            included.add(recipe_id)
            steps.append(
                BuildStep(
                    recipe_id=recipe_id,
                    target_dataset_id=outputs[0],
                    ordinal=len(steps),
                )
            )
    return steps
