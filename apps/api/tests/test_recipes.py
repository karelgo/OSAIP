"""Recipes CRUD + graph invariants (arity, single-producer, cycle), CP-1/CP-2
propagation, before/after config audit (ADR-0007 §3), and config-hash round-trip
stability (ADR-0007 §2).

Source datasets are inserted straight through the ORM (current_version=1 + a
DatasetVersion) so the suite needs no engine/upload round-trip — recipes never touch
the engine, only the graph tables.
"""

from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import Dataset, DatasetVersion, Project, Recipe
from osaip_shared.ids import new_id
from osaip_shared.recipes import config_hash

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]

PREPARE = {"kind": "prepare", "steps": [{"op": "rename", "mapping": {"a": "b"}}]}
JOIN = {"kind": "join", "how": "inner", "on": [{"left": "id", "right": "id"}]}


async def _project(client: httpx.AsyncClient, key: str) -> None:
    assert (
        await client.post("/api/v1/projects", json={"key": key, "name": key})
    ).status_code == 201


async def _pid(db_session: AsyncSession, key: str) -> str:
    """Project id — needed to scope db reads (the container DB is session-shared, so
    plain name lookups collide across projects)."""
    return str(
        (await db_session.execute(select(Project.id).where(Project.key == key))).scalar_one()
    )


async def _seed_source(
    db_session: AsyncSession,
    key: str,
    name: str,
    *,
    classification: str = "none",
    bbn_level: str | None = None,
    purpose_codes: list[str] | None = None,
    current_version: int = 1,
    row_count: int | None = 3,
) -> str:
    """Insert a producer-less source dataset (+ its current version) directly."""
    project_id = (
        await db_session.execute(select(Project.id).where(Project.key == key))
    ).scalar_one()
    dataset = Dataset(
        id=new_id(),
        project_id=project_id,
        name=name,
        kind="file",
        description="",
        classification=classification,
        bbn_level=bbn_level,
        legal_basis="Art 6(1)(e) AVG",
        purpose_codes=purpose_codes or ["analytics.internal"],
        params={},
        current_version=current_version,
    )
    db_session.add(dataset)
    await db_session.flush()
    if current_version > 0:
        db_session.add(
            DatasetVersion(
                id=new_id(),
                dataset_id=dataset.id,
                version=current_version,
                location=f"s3://bucket/{key}/{name}/v{current_version}.parquet",
                format="parquet",
                schema_json={"columns": []},
                row_count=row_count,
                row_count_kind="exact",
            )
        )
    await db_session.commit()
    return str(dataset.id)


async def test_create_recipe_full_flow(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("rcp-admin", "rcp-admin@osaip.dev")
    await _project(admin, "rcp1")
    await _seed_source(db_session, "rcp1", "orders", purpose_codes=["analytics.internal", "audit"])

    created = await admin.post(
        "/api/v1/projects/rcp1/recipes",
        json={
            "name": "clean-orders",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["orders"],
            "output_names": ["orders_clean"],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "prepare"
    assert body["input_datasets"] == ["orders"]
    assert body["output_datasets"] == ["orders_clean"]
    assert body["status"] == "active"
    # CP-2: recipe + output purposes = intersection of inputs (here, the single input's)
    assert body["purpose_codes"] == ["analytics.internal", "audit"]
    assert body["config_hash"] == config_hash(PREPARE)

    # the output dataset was provisioned never-built (current_version 0) and producer-owned
    output = (
        await db_session.execute(
            select(Dataset).where(
                Dataset.name == "orders_clean", Dataset.project_id == await _pid(db_session, "rcp1")
            )
        )
    ).scalar_one()
    assert output.current_version == 0
    assert output.purpose_codes == ["analytics.internal", "audit"]

    detail = await admin.get(f"/api/v1/projects/rcp1/recipes/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "clean-orders"

    listed = await admin.get("/api/v1/projects/rcp1/recipes")
    assert listed.status_code == 200
    assert [r["name"] for r in listed.json()["items"]] == ["clean-orders"]


async def test_object_ref_created(login_as: LoginAs, db_session: AsyncSession) -> None:
    from sqlalchemy import text

    admin = await login_as("rcp-ref", "rcp-ref@osaip.dev")
    await _project(admin, "rcpref")
    await _seed_source(db_session, "rcpref", "src")
    created = await admin.post(
        "/api/v1/projects/rcpref/recipes",
        json={
            "name": "r1",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["src"],
            "output_names": ["out1"],
        },
    )
    assert created.status_code == 201, created.text
    ref = (
        await db_session.execute(
            text(
                "SELECT url_path FROM object_refs r JOIN projects p ON p.id = r.project_id "
                "WHERE r.kind='recipe' AND r.name='r1' AND p.key='rcpref'"
            )
        )
    ).scalar_one()
    assert ref == "/p/rcpref?sel=recipe:r1"


async def test_viewer_cannot_create(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("rcp-admin2", "rcp-admin2@osaip.dev")
    await _project(admin, "rcp2")
    await _seed_source(db_session, "rcp2", "src")
    members = [
        {"email": "rcp-admin2@osaip.dev", "role": "admin"},
        {"email": "rcp-viewer@osaip.dev", "role": "viewer"},
    ]
    viewer = await login_as("rcp-viewer", "rcp-viewer@osaip.dev")
    assert (
        await admin.put("/api/v1/projects/rcp2/members", json={"members": members})
    ).status_code == 200
    blocked = await viewer.post(
        "/api/v1/projects/rcp2/recipes",
        json={
            "name": "r1",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["src"],
            "output_names": ["out1"],
        },
    )
    assert blocked.status_code == 403
    assert blocked.json()["type"] == "urn:osaip:problem:forbidden"


async def test_arity_error(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("rcp-admin3", "rcp-admin3@osaip.dev")
    await _project(admin, "rcp3")
    await _seed_source(db_session, "rcp3", "src")
    bad = await admin.post(
        "/api/v1/projects/rcp3/recipes",
        json={
            "name": "j1",
            "kind": "join",
            "config": JOIN,
            "input_dataset_names": ["src"],  # join needs 2
            "output_names": ["joined"],
        },
    )
    assert bad.status_code == 422
    assert bad.json()["type"] == "urn:osaip:problem:validation"


async def test_bad_config(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("rcp-admin4", "rcp-admin4@osaip.dev")
    await _project(admin, "rcp4")
    await _seed_source(db_session, "rcp4", "src")
    bad = await admin.post(
        "/api/v1/projects/rcp4/recipes",
        json={
            "name": "r1",
            "kind": "prepare",
            "config": {"kind": "prepare", "steps": []},  # min_length=1 violated
            "input_dataset_names": ["src"],
            "output_names": ["out1"],
        },
    )
    assert bad.status_code == 422
    assert bad.json()["type"] == "urn:osaip:problem:validation"


async def test_single_producer(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("rcp-admin5", "rcp-admin5@osaip.dev")
    await _project(admin, "rcp5")
    await _seed_source(db_session, "rcp5", "src")
    first = await admin.post(
        "/api/v1/projects/rcp5/recipes",
        json={
            "name": "ra",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["src"],
            "output_names": ["shared_out"],
        },
    )
    assert first.status_code == 201, first.text
    second = await admin.post(
        "/api/v1/projects/rcp5/recipes",
        json={
            "name": "rb",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["src"],
            "output_names": ["shared_out"],  # already produced by "ra"
        },
    )
    assert second.status_code == 409
    assert second.json()["type"] == "urn:osaip:problem:single-producer"


async def test_cycle_rejected(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("rcp-admin6", "rcp-admin6@osaip.dev")
    await _project(admin, "rcp6")
    await _seed_source(db_session, "rcp6", "a")
    # A: a → b
    first = await admin.post(
        "/api/v1/projects/rcp6/recipes",
        json={
            "name": "mk-b",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["a"],
            "output_names": ["b"],
        },
    )
    assert first.status_code == 201, first.text
    # B: b → a  (would close the loop)
    second = await admin.post(
        "/api/v1/projects/rcp6/recipes",
        json={
            "name": "mk-a",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["b"],
            "output_names": ["a"],
        },
    )
    assert second.status_code == 422
    assert second.json()["type"] == "urn:osaip:problem:cycle"


async def test_patch_audits_before_after_config(
    login_as: LoginAs, db_session: AsyncSession
) -> None:
    from sqlalchemy import text

    admin = await login_as("rcp-admin7", "rcp-admin7@osaip.dev")
    await _project(admin, "rcp7")
    await _seed_source(db_session, "rcp7", "src")
    created = await admin.post(
        "/api/v1/projects/rcp7/recipes",
        json={
            "name": "r1",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["src"],
            "output_names": ["out1"],
        },
    )
    recipe_id = created.json()["id"]
    new_config = {"kind": "prepare", "steps": [{"op": "rename", "mapping": {"x": "y"}}]}
    patched = await admin.patch(
        f"/api/v1/projects/rcp7/recipes/{recipe_id}",
        json={"config": new_config},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["config_hash"] == config_hash(new_config)

    details = (
        await db_session.execute(
            text(
                "SELECT details FROM audit_log WHERE object_kind='recipe' "
                "AND action='recipe.updated' AND object_id='r1' ORDER BY seq DESC LIMIT 1"
            )
        )
    ).scalar_one()
    assert "before" in details and "after" in details
    assert "a" in details["before"] and "x" in details["after"]  # full config captured


async def test_archive_frees_output_producer(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("rcp-admin8", "rcp-admin8@osaip.dev")
    await _project(admin, "rcp8")
    await _seed_source(db_session, "rcp8", "src")
    created = await admin.post(
        "/api/v1/projects/rcp8/recipes",
        json={
            "name": "ra",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["src"],
            "output_names": ["out1"],
        },
    )
    recipe_id = created.json()["id"]
    archived = await admin.delete(f"/api/v1/projects/rcp8/recipes/{recipe_id}")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    # out1 is producer-less again → a new recipe may adopt it
    reused = await admin.post(
        "/api/v1/projects/rcp8/recipes",
        json={
            "name": "rb",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["src"],
            "output_names": ["out1"],
        },
    )
    assert reused.status_code == 201, reused.text


async def test_config_hash_roundtrip_stable(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("rcp-admin9", "rcp-admin9@osaip.dev")
    await _project(admin, "rcp9")
    await _seed_source(db_session, "rcp9", "src")
    created = await admin.post(
        "/api/v1/projects/rcp9/recipes",
        json={
            "name": "r1",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["src"],
            "output_names": ["out1"],
        },
    )
    assert created.status_code == 201, created.text
    # reload the row straight from the DB and re-hash the jsonb read-back
    recipe = (
        await db_session.execute(
            select(Recipe).where(
                Recipe.name == "r1", Recipe.project_id == await _pid(db_session, "rcp9")
            )
        )
    ).scalar_one()
    assert config_hash(recipe.config) == recipe.config_hash
