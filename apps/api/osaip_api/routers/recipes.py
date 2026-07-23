"""Recipes: transformation nodes in the Flow (spec §4, ADR-0007). CRUD with the graph
invariants — valid arity, single producer, no cycles — plus CP-1/CP-2 propagation onto
the (provisioned, never-built) output datasets.

Mutation ordering everywhere: mutate → publish_event → write_audit LAST → commit
(ADR-0005 advisory-lock contract). Server-side onupdate columns are refreshed async
after commit (a plain read would raise MissingGreenlet under asyncpg).
"""

import base64
import json
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.events import publish_event
from osaip_api.models import Dataset, Recipe, RecipeInput, RecipeOutput
from osaip_api.object_refs import remove_object_ref, upsert_object_ref
from osaip_api.permissions import ProjectContext, load_project_context
from osaip_api.problem import Problem
from osaip_api.propagation import (
    apply_classification_floor,
    legal_basis_union,
    purpose_intersection,
)
from osaip_api.recipes_service import (
    check_arity,
    load_graph,
    provision_outputs,
    would_create_cycle,
)
from osaip_api.schemas import RecipeListOut, RecipeOut
from osaip_shared.ids import new_id
from osaip_shared.recipes import (
    GroupConfig,
    JoinConfig,
    PrepareConfig,
    PythonConfig,
    SampleConfig,
    SplitConfig,
    SqlConfig,
    StackConfig,
    config_hash,
)

router = APIRouter(prefix="/projects/{key}/recipes", tags=["recipes"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")

RecipeKind = Literal["prepare", "join", "group", "stack", "split", "sample", "sql", "python"]

# kind → the pydantic config model that validates its `config` payload (osaip_shared).
_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "prepare": PrepareConfig,
    "join": JoinConfig,
    "group": GroupConfig,
    "stack": StackConfig,
    "split": SplitConfig,
    "sample": SampleConfig,
    "sql": SqlConfig,
    "python": PythonConfig,
}


class RecipeCreate(BaseModel):
    name: str = Field(pattern=_NAME_RE.pattern)
    kind: RecipeKind
    config: dict[str, Any]
    input_dataset_names: list[str] = Field(min_length=1, max_length=64)
    output_names: list[str] = Field(min_length=1, max_length=8)
    purpose_codes: list[str] | None = Field(default=None, max_length=20)


class RecipePatch(BaseModel):
    name: str | None = Field(default=None, pattern=_NAME_RE.pattern)
    config: dict[str, Any] | None = None
    purpose_codes: list[str] | None = Field(default=None, max_length=20)
    input_dataset_names: list[str] | None = Field(default=None, min_length=1, max_length=64)
    output_names: list[str] | None = Field(default=None, min_length=1, max_length=8)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _validate_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    """Validate `config` against the model for `kind` and return the canonical dict
    (by_alias, so `as_` → `as` round-trips through storage and the config hash)."""
    declared = config.get("kind")
    if declared is not None and declared != kind:
        raise Problem(
            422,
            title="Config kind mismatch",
            detail=f"config.kind {declared!r} must equal the recipe kind {kind!r}.",
            hint="Drop the kind from config, or make it match the recipe kind.",
            slug="validation",
        )
    try:
        model = _CONFIG_MODELS[kind].model_validate({**config, "kind": kind})
    except ValidationError as exc:
        errors = exc.errors()
        detail = f"Invalid {kind} config"
        if errors:
            loc = ".".join(str(part) for part in errors[0]["loc"])
            detail += f" at {loc}: {errors[0]['msg']}." if loc else f": {errors[0]['msg']}."
        else:
            detail += "."
        raise Problem(
            422,
            title="Invalid recipe config",
            detail=detail,
            hint="Fix the recipe config for this kind and retry.",
            slug="validation",
        ) from exc
    return model.model_dump(by_alias=True)


async def _resolve_inputs(
    session: AsyncSession, ctx: ProjectContext, names: list[str]
) -> list[Dataset]:
    """Active input datasets in the exact order requested (404 if any is missing)."""
    rows = (
        (
            await session.execute(
                select(Dataset).where(
                    Dataset.project_id == ctx.project.id,
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
            title="Input dataset not found",
            detail=f"No active dataset(s) named {sorted(missing)} in this project.",
            hint="Check the input dataset names.",
            slug="not-found",
        )
    return [by_name[name] for name in names]


async def _input_datasets(session: AsyncSession, recipe_id: Any) -> list[Dataset]:
    rows = (
        (
            await session.execute(
                select(Dataset)
                .join(RecipeInput, RecipeInput.dataset_id == Dataset.id)
                .where(RecipeInput.recipe_id == recipe_id)
                .order_by(RecipeInput.ordinal)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _output_datasets(session: AsyncSession, recipe_id: Any) -> list[Dataset]:
    rows = (
        (
            await session.execute(
                select(Dataset)
                .join(RecipeOutput, RecipeOutput.dataset_id == Dataset.id)
                .where(RecipeOutput.recipe_id == recipe_id)
                .order_by(RecipeOutput.ordinal)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _payload(recipe: Recipe, input_names: list[str], output_names: list[str]) -> dict[str, Any]:
    return {
        "id": str(recipe.id),
        "name": recipe.name,
        "kind": recipe.kind,
        "config": recipe.config,
        "config_hash": recipe.config_hash,
        "purpose_codes": recipe.purpose_codes,
        "status": recipe.status,
        "input_datasets": input_names,
        "output_datasets": output_names,
        "created_at": recipe.created_at.isoformat(),
        "updated_at": recipe.updated_at.isoformat(),
    }


async def _get_recipe(session: AsyncSession, ctx: ProjectContext, recipe_id: str) -> Recipe:
    recipe = (
        await session.execute(
            select(Recipe).where(
                Recipe.id == recipe_id,
                Recipe.project_id == ctx.project.id,
                Recipe.status == "active",
            )
        )
    ).scalar_one_or_none()
    if recipe is None:
        raise Problem(
            404,
            title="Recipe not found",
            detail="No such active recipe in this project.",
            hint="Check the recipe id.",
            slug="not-found",
        )
    return recipe


# ── Create ─────────────────────────────────────────────────────────────────────────


@router.post("", status_code=201, response_model=RecipeOut)
async def create_recipe(
    key: str, body: RecipeCreate, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="editor")

    duplicate = (
        await session.execute(
            select(Recipe).where(Recipe.project_id == ctx.project.id, Recipe.name == body.name)
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise Problem(
            409,
            title="Name already in use",
            detail=f"A recipe named {body.name!r} already exists in this project.",
            hint="Pick a different name (archived recipes keep their name).",
            slug="conflict",
        )

    config = _validate_config(body.kind, body.config)
    inputs = await _resolve_inputs(session, ctx, body.input_dataset_names)
    check_arity(body.kind, len(inputs))

    # CP-2: recipe + output purposes are the intersection of inputs unless overridden.
    purposes = (
        body.purpose_codes if body.purpose_codes is not None else purpose_intersection(inputs)
    )

    # Outputs must exist (or be adopted producer-less) before the cycle check, which
    # reasons over real dataset ids. They roll back with the request if we later raise.
    outputs = await provision_outputs(
        session,
        project_id=ctx.project.id,
        recipe_kind=body.kind,
        output_names=body.output_names,
        legal_basis=legal_basis_union(inputs),
        purpose_codes=purposes,
        created_by=user.id,
    )

    recipe_id = new_id()
    graph = await load_graph(session, ctx.project.id)
    if would_create_cycle(
        graph,
        recipe_id=recipe_id,
        input_dataset_ids=[dataset.id for dataset in inputs],
        output_dataset_ids=[dataset.id for dataset in outputs],
    ):
        raise Problem(
            422,
            title="Recipe would create a cycle",
            detail="Wiring these inputs to these outputs makes the flow graph cyclic.",
            hint="A dataset cannot (transitively) depend on itself.",
            slug="cycle",
        )

    recipe = Recipe(
        id=recipe_id,
        project_id=ctx.project.id,
        name=body.name,
        kind=body.kind,
        config=config,
        config_hash=config_hash(config),
        purpose_codes=purposes,
        created_by=user.id,
    )
    session.add(recipe)
    await session.flush()
    for ordinal, dataset in enumerate(inputs):
        session.add(RecipeInput(recipe_id=recipe.id, dataset_id=dataset.id, ordinal=ordinal))
    for ordinal, dataset in enumerate(outputs):
        session.add(RecipeOutput(recipe_id=recipe.id, dataset_id=dataset.id, ordinal=ordinal))
    try:
        await session.flush()
    except IntegrityError as exc:
        # Belt-and-braces: provision_outputs already rejects an already-produced output,
        # but the global unique constraint on recipe_outputs.dataset_id is the real guard.
        raise Problem(
            409,
            title="Dataset already produced",
            detail="One of these outputs is already produced by another recipe (single producer).",
            hint="Pick a different output name.",
            slug="single-producer",
        ) from exc

    for output in outputs:
        apply_classification_floor(output, inputs)

    input_names = [dataset.name for dataset in inputs]
    output_names = [dataset.name for dataset in outputs]

    await upsert_object_ref(
        session,
        kind="recipe",
        project_id=ctx.project.id,
        name=recipe.name,
        description="",
        url_path=f"/p/{ctx.project.key}?sel=recipe:{recipe.name}",
    )
    await publish_event(
        session,
        topic="flow",
        type="recipe.created",
        project_id=ctx.project.id,
        payload={"id": str(recipe.id), "name": recipe.name},
    )
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="recipe.created",
        object_kind="recipe",
        object_id=recipe.name,
        details={"kind": body.kind, "before": None},
        ip=_client_ip(request),
    )
    await session.commit()
    await session.refresh(recipe)
    return _payload(recipe, input_names, output_names)


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


@router.get("", response_model=RecipeListOut)
async def list_recipes(
    key: str,
    user: CurrentUser,
    session: DbSession,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    limit = max(1, min(limit, 200))
    query = (
        select(Recipe)
        .where(Recipe.project_id == ctx.project.id, Recipe.status == "active")
        .order_by(Recipe.name)
        .limit(limit + 1)
    )
    if cursor:
        query = query.where(Recipe.name > _decode_cursor(cursor))
    recipes = (await session.execute(query)).scalars().all()
    has_more = len(recipes) > limit
    recipes = recipes[:limit]
    items = []
    for recipe in recipes:
        input_names = [d.name for d in await _input_datasets(session, recipe.id)]
        output_names = [d.name for d in await _output_datasets(session, recipe.id)]
        items.append(_payload(recipe, input_names, output_names))
    return {
        "items": items,
        "next_cursor": _encode_cursor(recipes[-1].name) if has_more and recipes else None,
    }


@router.get("/{recipe_id}", response_model=RecipeOut)
async def get_recipe(
    key: str, recipe_id: str, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    recipe = await _get_recipe(session, ctx, recipe_id)
    input_names = [d.name for d in await _input_datasets(session, recipe.id)]
    output_names = [d.name for d in await _output_datasets(session, recipe.id)]
    return _payload(recipe, input_names, output_names)


# ── Mutations ────────────────────────────────────────────────────────────────────


@router.patch("/{recipe_id}", response_model=RecipeOut)
async def patch_recipe(
    key: str,
    recipe_id: str,
    body: RecipePatch,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="editor")
    recipe = await _get_recipe(session, ctx, recipe_id)
    old_config = dict(recipe.config)
    old_name = recipe.name
    changed: list[str] = []

    if body.name is not None and body.name != recipe.name:
        duplicate = (
            await session.execute(
                select(Recipe).where(Recipe.project_id == ctx.project.id, Recipe.name == body.name)
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise Problem(
                409,
                title="Name already in use",
                detail=f"A recipe named {body.name!r} already exists in this project.",
                hint="Pick a different name.",
                slug="conflict",
            )
        recipe.name = body.name
        changed.append("name")

    if body.config is not None:
        recipe.config = _validate_config(recipe.kind, body.config)
        recipe.config_hash = config_hash(recipe.config)
        changed.append("config")

    if body.purpose_codes is not None:
        recipe.purpose_codes = body.purpose_codes
        changed.append("purpose_codes")

    inputs_changed = body.input_dataset_names is not None
    outputs_changed = body.output_names is not None
    if inputs_changed or outputs_changed:
        inputs = (
            await _resolve_inputs(session, ctx, body.input_dataset_names)
            if body.input_dataset_names is not None
            else await _input_datasets(session, recipe.id)
        )
        check_arity(recipe.kind, len(inputs))

        if outputs_changed:
            # Free this recipe's current outputs so provision can re-adopt or replace
            # them (and so the graph the cycle check sees carries no stale producer).
            await session.execute(delete(RecipeOutput).where(RecipeOutput.recipe_id == recipe.id))
            await session.flush()
            outputs = await provision_outputs(
                session,
                project_id=ctx.project.id,
                recipe_kind=recipe.kind,
                output_names=body.output_names or [],
                legal_basis=legal_basis_union(inputs),
                purpose_codes=recipe.purpose_codes,
                created_by=user.id,
            )
        else:
            outputs = await _output_datasets(session, recipe.id)

        await session.execute(delete(RecipeInput).where(RecipeInput.recipe_id == recipe.id))
        await session.flush()

        graph = await load_graph(session, ctx.project.id)
        if would_create_cycle(
            graph,
            recipe_id=recipe.id,
            input_dataset_ids=[dataset.id for dataset in inputs],
            output_dataset_ids=[dataset.id for dataset in outputs],
        ):
            raise Problem(
                422,
                title="Recipe would create a cycle",
                detail="Rewiring these inputs to these outputs makes the flow graph cyclic.",
                hint="A dataset cannot (transitively) depend on itself.",
                slug="cycle",
            )

        for ordinal, dataset in enumerate(inputs):
            session.add(RecipeInput(recipe_id=recipe.id, dataset_id=dataset.id, ordinal=ordinal))
        if outputs_changed:
            for ordinal, dataset in enumerate(outputs):
                session.add(
                    RecipeOutput(recipe_id=recipe.id, dataset_id=dataset.id, ordinal=ordinal)
                )
        try:
            await session.flush()
        except IntegrityError as exc:
            raise Problem(
                409,
                title="Dataset already produced",
                detail="One of these outputs is already produced by another recipe "
                "(single producer).",
                hint="Pick a different output name.",
                slug="single-producer",
            ) from exc

        if inputs_changed:
            for output in outputs:
                apply_classification_floor(output, inputs)
            changed.append("inputs")
        if outputs_changed:
            changed.append("outputs")

    if changed:
        if "name" in changed:
            await remove_object_ref(
                session, kind="recipe", project_id=ctx.project.id, name=old_name
            )
            await upsert_object_ref(
                session,
                kind="recipe",
                project_id=ctx.project.id,
                name=recipe.name,
                description="",
                url_path=f"/p/{ctx.project.key}?sel=recipe:{recipe.name}",
            )
        await publish_event(
            session,
            topic="flow",
            type="recipe.updated",
            project_id=ctx.project.id,
            payload={"id": str(recipe.id), "name": recipe.name},
        )
        # ADR-0007 §3: recipe mutations write the full before/after config (JSON-encoded
        # so a `sample` fraction — a float — survives the audit's no-floats rule).
        await write_audit(
            session,
            actor_id=user.id,
            project_id=ctx.project.id,
            action="recipe.updated",
            object_kind="recipe",
            object_id=recipe.name,
            details={
                "changed": changed,
                "before": json.dumps(old_config, sort_keys=True, ensure_ascii=False),
                "after": json.dumps(recipe.config, sort_keys=True, ensure_ascii=False),
            },
            ip=_client_ip(request),
        )
    await session.commit()
    await session.refresh(recipe)
    input_names = [d.name for d in await _input_datasets(session, recipe.id)]
    output_names = [d.name for d in await _output_datasets(session, recipe.id)]
    return _payload(recipe, input_names, output_names)


@router.delete("/{recipe_id}", response_model=RecipeOut)
async def archive_recipe(
    key: str, recipe_id: str, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="editor")
    recipe = await _get_recipe(session, ctx, recipe_id)
    input_names = [d.name for d in await _input_datasets(session, recipe.id)]
    output_names = [d.name for d in await _output_datasets(session, recipe.id)]

    recipe.status = "archived"
    # Drop the output rows so the output dataset becomes producer-less again (its name
    # can be re-wired to a new recipe). The output dataset itself is NOT archived.
    await session.execute(delete(RecipeOutput).where(RecipeOutput.recipe_id == recipe.id))
    await remove_object_ref(session, kind="recipe", project_id=ctx.project.id, name=recipe.name)
    await publish_event(
        session,
        topic="flow",
        type="recipe.archived",
        project_id=ctx.project.id,
        payload={"id": str(recipe.id), "name": recipe.name},
    )
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="recipe.archived",
        object_kind="recipe",
        object_id=recipe.name,
        details={},
        ip=_client_ip(request),
    )
    await session.commit()
    await session.refresh(recipe)
    return _payload(recipe, input_names, output_names)
