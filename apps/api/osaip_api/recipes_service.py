"""Recipe graph invariants (spec §4): single producer, no cycles, valid arity, and
output-dataset provisioning. Shared by the recipes router and the flow view-model."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import Dataset, Recipe, RecipeInput, RecipeOutput
from osaip_api.problem import Problem
from osaip_shared.recipes import INPUT_ARITY, OUTPUT_ARITY


@dataclass
class RecipeGraph:
    """The project's active recipe DAG as adjacency over dataset ids."""

    # dataset_id -> recipe_id that produces it
    producer: dict[uuid.UUID, uuid.UUID]
    # recipe_id -> input dataset_ids
    inputs: dict[uuid.UUID, list[uuid.UUID]]
    # recipe_id -> output dataset_ids
    outputs: dict[uuid.UUID, list[uuid.UUID]]


async def load_graph(session: AsyncSession, project_id: uuid.UUID) -> RecipeGraph:
    recipes = (
        (
            await session.execute(
                select(Recipe.id).where(Recipe.project_id == project_id, Recipe.status == "active")
            )
        )
        .scalars()
        .all()
    )
    recipe_ids = set(recipes)
    producer: dict[uuid.UUID, uuid.UUID] = {}
    inputs: dict[uuid.UUID, list[uuid.UUID]] = {rid: [] for rid in recipe_ids}
    outputs: dict[uuid.UUID, list[uuid.UUID]] = {rid: [] for rid in recipe_ids}

    for recipe_id, dataset_id, _ in (
        await session.execute(
            select(RecipeInput.recipe_id, RecipeInput.dataset_id, RecipeInput.ordinal)
            .where(RecipeInput.recipe_id.in_(recipe_ids))
            .order_by(RecipeInput.ordinal)
        )
    ).all():
        inputs[recipe_id].append(dataset_id)
    for recipe_id, dataset_id, _ in (
        await session.execute(
            select(RecipeOutput.recipe_id, RecipeOutput.dataset_id, RecipeOutput.ordinal)
            .where(RecipeOutput.recipe_id.in_(recipe_ids))
            .order_by(RecipeOutput.ordinal)
        )
    ).all():
        outputs[recipe_id].append(dataset_id)
        producer[dataset_id] = recipe_id
    return RecipeGraph(producer=producer, inputs=inputs, outputs=outputs)


def check_arity(kind: str, input_count: int) -> None:
    lo, hi = INPUT_ARITY[kind]
    if input_count < lo or (hi is not None and input_count > hi):
        bound = f"{lo}" if lo == hi else (f"{lo}+" if hi is None else f"{lo}-{hi}")
        raise Problem(
            422,
            title="Wrong number of inputs",
            detail=f"A {kind} recipe takes {bound} input(s); got {input_count}.",
            hint="Adjust the recipe's inputs.",
            slug="validation",
        )


def would_create_cycle(
    graph: RecipeGraph,
    *,
    recipe_id: uuid.UUID,
    input_dataset_ids: list[uuid.UUID],
    output_dataset_ids: list[uuid.UUID],
) -> bool:
    """True if wiring recipe_id (inputs→outputs) makes the dataset dependency graph
    cyclic. Walks from each input back through producers; a cycle exists if any
    output dataset is reachable upstream of an input."""
    outputs = set(output_dataset_ids)
    # Overlay the candidate edges on the current graph.
    producer = dict(graph.producer)
    inputs = dict(graph.inputs)
    for dataset_id in output_dataset_ids:
        producer[dataset_id] = recipe_id
    inputs[recipe_id] = input_dataset_ids

    seen: set[uuid.UUID] = set()

    def upstream_datasets(dataset_id: uuid.UUID) -> bool:
        # DFS over datasets; returns True if we reach one of `outputs`.
        stack = [dataset_id]
        while stack:
            current = stack.pop()
            if current in outputs:
                return True
            if current in seen:
                continue
            seen.add(current)
            prod = producer.get(current)
            if prod is not None:
                stack.extend(inputs.get(prod, []))
        return False

    return any(upstream_datasets(dataset_id) for dataset_id in input_dataset_ids)


async def provision_outputs(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    recipe_kind: str,
    output_names: list[str],
    legal_basis: str,
    purpose_codes: list[str],
    created_by: uuid.UUID | None,
) -> list[Dataset]:
    """Create (or adopt a producer-less) output dataset per name. CP-2 metadata is
    computed by the caller (intersection of input purposes)."""
    expected = OUTPUT_ARITY[recipe_kind]
    if len(output_names) != expected:
        raise Problem(
            422,
            title="Wrong number of outputs",
            detail=f"A {recipe_kind} recipe produces {expected} output(s).",
            hint="Provide the right number of output names.",
            slug="validation",
        )
    datasets: list[Dataset] = []
    for name in output_names:
        existing = (
            await session.execute(
                select(Dataset).where(Dataset.project_id == project_id, Dataset.name == name)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status == "archived":
                raise Problem(
                    409,
                    title="Name is archived",
                    detail=f"An archived dataset named {name!r} exists; names are reserved.",
                    hint="Choose a different output name.",
                    slug="conflict",
                )
            # Adopt only if it is already producer-less (no active RecipeOutput row).
            has_producer = (
                await session.execute(
                    select(RecipeOutput).where(RecipeOutput.dataset_id == existing.id)
                )
            ).scalar_one_or_none()
            if has_producer is not None:
                raise Problem(
                    409,
                    title="Dataset already produced",
                    detail=f"{name!r} is already the output of another recipe (single producer).",
                    hint="Pick a different output name.",
                    slug="single-producer",
                )
            datasets.append(existing)
            continue
        dataset = Dataset(
            project_id=project_id,
            name=name,
            kind="file",
            description="",
            classification="none",
            legal_basis=legal_basis,
            purpose_codes=purpose_codes,
            params={"produced_by_recipe": True},
            current_version=0,
            created_by=created_by,
        )
        session.add(dataset)
        datasets.append(dataset)
    await session.flush()
    return datasets
