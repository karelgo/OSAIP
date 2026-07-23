"""Build resolution (the AC-2 stale-subset semantics) + the builds/jobs endpoints.

Resolution reads only current_version + config hashes, so the graph is seeded through
the ORM (no engine round-trip). Full execution is covered in test_executor.py.
"""

import uuid
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.build_service import resolve_build
from osaip_api.models import (
    Dataset,
    DatasetVersion,
    Project,
    Recipe,
    RecipeInput,
    RecipeOutput,
)
from osaip_shared.ids import new_id
from osaip_shared.recipes import config_hash

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]


async def _project(db: AsyncSession, key: str) -> Project:
    project = Project(key=key, name=key, storage_prefix=f"projects/{key}")
    db.add(project)
    await db.flush()
    return project


async def _source(db: AsyncSession, project: Project, name: str) -> Dataset:
    """A built source dataset (current_version=1, no producer)."""
    dataset = Dataset(
        id=new_id(),
        project_id=project.id,
        name=name,
        kind="file",
        legal_basis="demo",
        purpose_codes=["demo"],
        current_version=1,
    )
    db.add(dataset)
    await db.flush()
    db.add(
        DatasetVersion(
            id=new_id(),
            dataset_id=dataset.id,
            version=1,
            location="s3://b/x.parquet",
            format="parquet",
            schema_json={"columns": []},
        )
    )
    await db.flush()
    return dataset


async def _recipe(
    db: AsyncSession, project: Project, name: str, inp: Dataset, config: dict
) -> tuple[Recipe, Dataset]:
    """A prepare recipe `inp → <name>_out` (output never-built)."""
    recipe = Recipe(
        id=new_id(),
        project_id=project.id,
        name=name,
        kind="prepare",
        config=config,
        config_hash=config_hash(config),
        purpose_codes=["demo"],
    )
    output = Dataset(
        id=new_id(),
        project_id=project.id,
        name=f"{name}_out",
        kind="file",
        legal_basis="demo",
        purpose_codes=["demo"],
        current_version=0,
    )
    db.add_all([recipe, output])
    await db.flush()
    db.add(RecipeInput(recipe_id=recipe.id, dataset_id=inp.id, ordinal=0))
    db.add(RecipeOutput(recipe_id=recipe.id, dataset_id=output.id, ordinal=0))
    await db.flush()
    return recipe, output


_CFG_A = {"kind": "prepare", "steps": [{"op": "dedupe", "subset": []}]}
_CFG_B = {"kind": "prepare", "steps": [{"op": "sample", "n": 5}]}


async def _mark_built(
    db: AsyncSession, recipe: Recipe, output: Dataset, inputs: list[Dataset]
) -> None:
    """Simulate a build: bump the output + record a fresh version with matching hash."""
    output.current_version += 1
    db.add(
        DatasetVersion(
            id=new_id(),
            dataset_id=output.id,
            version=output.current_version,
            location="s3://b/o.parquet",
            format="parquet",
            schema_json={"columns": []},
            recipe_config_hash=recipe.config_hash,
            input_versions={str(i.id): i.current_version for i in inputs},
        )
    )
    await db.flush()


async def test_resolve_stale_subset(db_session: AsyncSession) -> None:
    # a(source) → [r1] → b → [r2] → c
    project = await _project(db_session, "bld1")
    a = await _source(db_session, project, "a")
    r1, b = await _recipe(db_session, project, "r1", a, dict(_CFG_A))
    r2, c = await _recipe(db_session, project, "r2", b, dict(_CFG_A))
    await db_session.commit()

    # both never-built → 2 steps in topo order (r1 before r2)
    steps = await resolve_build(db_session, project, ["r2_out"], force=False)
    assert [s.recipe_id for s in steps] == [r1.id, r2.id]

    # build both → fresh → 0 steps
    await _mark_built(db_session, r1, b, [a])
    await _mark_built(db_session, r2, c, [b])
    await db_session.commit()
    assert await resolve_build(db_session, project, ["r2_out"], force=False) == []

    # force → all steps regardless of freshness
    forced = await resolve_build(db_session, project, ["r2_out"], force=True)
    assert [s.recipe_id for s in forced] == [r1.id, r2.id]

    # edit r1's config → b stale → build c rebuilds r1 AND r2 (downstream), not just r2
    r1.config = dict(_CFG_B)
    r1.config_hash = config_hash(r1.config)
    await db_session.commit()
    steps = await resolve_build(db_session, project, ["r2_out"], force=False)
    assert [s.recipe_id for s in steps] == [r1.id, r2.id]

    # rebuild r1 only, then editing r2 alone → exactly 1 step (r2), r1 untouched (AC-2)
    await _mark_built(db_session, r1, b, [a])
    await db_session.commit()
    r2.config = dict(_CFG_B)
    r2.config_hash = config_hash(r2.config)
    await db_session.commit()
    steps = await resolve_build(db_session, project, ["r2_out"], force=False)
    assert [s.recipe_id for s in steps] == [r2.id]


async def test_source_dataset_cannot_be_built(db_session: AsyncSession) -> None:
    from osaip_api.problem import Problem

    project = await _project(db_session, "bld2")
    await _source(db_session, project, "raw")
    await db_session.commit()
    try:
        await resolve_build(db_session, project, ["raw"], force=False)
        raise AssertionError("expected a Problem")
    except Problem as exc:
        assert exc.status == 422 and exc.slug == "not-produced"


# ── endpoint tests ───────────────────────────────────────────────────────────────


async def _api_project(client: httpx.AsyncClient, key: str) -> None:
    assert (
        await client.post("/api/v1/projects", json={"key": key, "name": key})
    ).status_code == 201


async def _seed_buildable(client: httpx.AsyncClient, db_session: AsyncSession, key: str) -> None:
    """One source + one prepare recipe over it (output never-built), through the ORM but
    committed so the API session sees it."""
    project = (await db_session.execute(select(Project).where(Project.key == key))).scalar_one()
    src = await _source(db_session, project, "src")
    await _recipe(db_session, project, "clean", src, dict(_CFG_A))
    await db_session.commit()


async def test_build_endpoint_creates_job_and_coalesces(
    login_as: LoginAs, db_session: AsyncSession
) -> None:
    admin = await login_as("bld-admin", "bld-admin@osaip.dev")
    await _api_project(admin, "bldapi")
    await _seed_buildable(admin, db_session, "bldapi")

    created = await admin.post("/api/v1/projects/bldapi/builds", json={"targets": ["clean_out"]})
    assert created.status_code == 200, created.text
    job = created.json()
    assert job["status"] == "queued"
    assert len(job["steps"]) == 1

    # a second build of the same target coalesces onto the queued job
    again = await admin.post("/api/v1/projects/bldapi/builds", json={"targets": ["clean_out"]})
    assert again.status_code == 200
    assert again.json()["id"] == job["id"]


async def test_build_rbac_and_idempotency(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("bld-admin2", "bld-admin2@osaip.dev")
    await _api_project(admin, "bldapi2")
    await _seed_buildable(admin, db_session, "bldapi2")
    members = [
        {"email": "bld-admin2@osaip.dev", "role": "admin"},
        {"email": "bld-viewer@osaip.dev", "role": "viewer"},
    ]
    viewer = await login_as("bld-viewer", "bld-viewer@osaip.dev")
    await admin.put("/api/v1/projects/bldapi2/members", json={"members": members})
    assert (
        await viewer.post("/api/v1/projects/bldapi2/builds", json={"targets": ["clean_out"]})
    ).status_code == 403

    key = str(uuid.uuid4())
    first = await admin.post(
        "/api/v1/projects/bldapi2/builds",
        json={"targets": ["clean_out"]},
        headers={"idempotency-key": key},
    )
    replay = await admin.post(
        "/api/v1/projects/bldapi2/builds",
        json={"targets": ["clean_out"]},
        headers={"idempotency-key": key},
    )
    assert first.json()["id"] == replay.json()["id"]


async def test_cancel_queued_job(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("bld-admin3", "bld-admin3@osaip.dev")
    await _api_project(admin, "bldapi3")
    await _seed_buildable(admin, db_session, "bldapi3")
    job = (
        await admin.post("/api/v1/projects/bldapi3/builds", json={"targets": ["clean_out"]})
    ).json()
    cancelled = await admin.post(f"/api/v1/projects/bldapi3/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert all(s["status"] == "skipped" for s in cancelled.json()["steps"])
