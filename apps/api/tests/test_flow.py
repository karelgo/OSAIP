"""Flow view-model: node/edge shape and the per-dataset freshness status machine
(never_built → fresh → stale, ADR-0007 §2). input_versions is keyed by str(dataset_id).
"""

from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import Dataset, DatasetVersion, Project
from osaip_shared.ids import new_id

from .test_recipes import PREPARE, _project, _seed_source

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]


def _by_name(flow: dict, name: str) -> dict:
    return next(d for d in flow["datasets"] if d["name"] == name)


async def _build_output(
    db_session: AsyncSession,
    project_key: str,
    output_name: str,
    *,
    config_hash: str,
    input_versions: dict[str, int],
    version: int = 1,
) -> None:
    """Simulate a worker build: add a DatasetVersion carrying the producer's config
    hash + consumed input versions, and flip current_version."""
    dataset = (
        await db_session.execute(
            select(Dataset)
            .join(Project, Project.id == Dataset.project_id)
            .where(Dataset.name == output_name, Project.key == project_key)
        )
    ).scalar_one()
    db_session.add(
        DatasetVersion(
            id=new_id(),
            dataset_id=dataset.id,
            version=version,
            location=f"s3://bucket/{output_name}/v{version}.parquet",
            format="parquet",
            schema_json={"columns": []},
            row_count=3,
            row_count_kind="exact",
            recipe_config_hash=config_hash,
            input_versions=input_versions,
        )
    )
    dataset.current_version = version
    await db_session.commit()


async def test_flow_status_machine(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("flow-admin", "flow-admin@osaip.dev")
    await _project(admin, "flow1")
    src_id = await _seed_source(db_session, "flow1", "src")

    created = await admin.post(
        "/api/v1/projects/flow1/recipes",
        json={
            "name": "clean",
            "kind": "prepare",
            "config": PREPARE,
            "input_dataset_names": ["src"],
            "output_names": ["clean_out"],
        },
    )
    assert created.status_code == 201, created.text
    recipe_id = created.json()["id"]
    recipe_hash = created.json()["config_hash"]

    # 1) never built ────────────────────────────────────────────────────────────────
    flow = (await admin.get("/api/v1/projects/flow1/flow")).json()
    assert _by_name(flow, "src")["status"] == "source"
    assert _by_name(flow, "clean_out")["status"] == "never_built"
    # nodes + edges wiring
    assert {r["id"] for r in flow["recipes"]} == {recipe_id}
    assert {"from": "dataset:src", "to": f"recipe:{recipe_id}"} in flow["edges"]
    assert {"from": f"recipe:{recipe_id}", "to": "dataset:clean_out"} in flow["edges"]
    assert flow["capabilities"]["can_edit"] is True

    # 2) built with matching hash + consumed input v1 → fresh ─────────────────────────
    await _build_output(
        db_session, "flow1", "clean_out", config_hash=recipe_hash, input_versions={str(src_id): 1}
    )
    flow = (await admin.get("/api/v1/projects/flow1/flow")).json()
    assert _by_name(flow, "clean_out")["status"] == "fresh"
    assert _by_name(flow, "clean_out")["current_version"] == 1

    # 3) bump the input's current_version above what the build consumed → stale ────────
    src = (await db_session.execute(select(Dataset).where(Dataset.id == src_id))).scalar_one()
    src.current_version = 2
    db_session.add(
        DatasetVersion(
            id=new_id(),
            dataset_id=src.id,
            version=2,
            location="s3://bucket/src/v2.parquet",
            format="parquet",
            schema_json={"columns": []},
            row_count=4,
            row_count_kind="exact",
        )
    )
    await db_session.commit()
    flow = (await admin.get("/api/v1/projects/flow1/flow")).json()
    assert _by_name(flow, "clean_out")["status"] == "stale"

    # 4) re-build to consume input v2 → fresh again, then change recipe config → stale ─
    await _build_output(
        db_session,
        "flow1",
        "clean_out",
        config_hash=recipe_hash,
        input_versions={str(src_id): 2},
        version=2,
    )
    flow = (await admin.get("/api/v1/projects/flow1/flow")).json()
    assert _by_name(flow, "clean_out")["status"] == "fresh"

    changed = await admin.patch(
        f"/api/v1/projects/flow1/recipes/{recipe_id}",
        json={"config": {"kind": "prepare", "steps": [{"op": "rename", "mapping": {"p": "q"}}]}},
    )
    assert changed.status_code == 200
    flow = (await admin.get("/api/v1/projects/flow1/flow")).json()
    assert _by_name(flow, "clean_out")["status"] == "stale"  # config_hash drift


async def test_flow_etag_304(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("flow-admin2", "flow-admin2@osaip.dev")
    await _project(admin, "flow2")
    await _seed_source(db_session, "flow2", "src")
    first = await admin.get("/api/v1/projects/flow2/flow")
    assert first.status_code == 200
    etag = first.headers["etag"]
    again = await admin.get("/api/v1/projects/flow2/flow", headers={"if-none-match": etag})
    assert again.status_code == 304


async def test_flow_viewer_cannot_edit(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("flow-admin3", "flow-admin3@osaip.dev")
    await _project(admin, "flow3")
    await _seed_source(db_session, "flow3", "src")
    members = [
        {"email": "flow-admin3@osaip.dev", "role": "admin"},
        {"email": "flow-viewer@osaip.dev", "role": "viewer"},
    ]
    viewer = await login_as("flow-viewer", "flow-viewer@osaip.dev")
    await admin.put("/api/v1/projects/flow3/members", json={"members": members})
    flow = (await viewer.get("/api/v1/projects/flow3/flow")).json()
    assert flow["capabilities"]["can_edit"] is False
