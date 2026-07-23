"""Recipe preview (§6.3(3)): runs against real parquet inputs, honors a draft config,
and never writes a dataset version."""

from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]

CSV = b"order_id,amount,region\n1,10.0,NL\n2,20.0,BE\n3,30.0,NL\n"


async def _dataset_from_upload(client: httpx.AsyncClient, key: str, name: str) -> None:
    assert (await client.post("/api/v1/projects", json={"key": key, "name": key})).status_code in (
        201,
        409,
    )
    upload = await client.post(
        f"/api/v1/projects/{key}/uploads", files={"file": ("o.csv", CSV, "text/csv")}
    )
    assert upload.status_code == 201, upload.text
    created = await client.post(
        f"/api/v1/projects/{key}/datasets",
        json={
            "name": name,
            "source": {"kind": "upload", "upload_id": upload.json()["upload_id"]},
            "legal_basis": "demo",
            "purpose_codes": ["demo"],
        },
    )
    assert created.status_code == 201, created.text


async def test_prepare_preview_and_draft_config(
    duck_extensions: None, login_as: LoginAs, db_session: AsyncSession
) -> None:
    admin = await login_as("rp-admin", "rp-admin@osaip.dev")
    await _dataset_from_upload(admin, "rpp1", "orders")

    recipe = await admin.post(
        "/api/v1/projects/rpp1/recipes",
        json={
            "name": "enriched",
            "kind": "prepare",
            "config": {
                "steps": [{"op": "formula", "column": "vat", "expression": 'col("amount") * 0.21'}]
            },
            "input_dataset_names": ["orders"],
            "output_names": ["enriched"],
        },
    )
    assert recipe.status_code == 201, recipe.text
    recipe_id = recipe.json()["id"]

    # saved-config preview
    preview = await admin.post(f"/api/v1/projects/rpp1/recipes/{recipe_id}/preview", json={})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert "vat" in {c["name"] for c in body["columns"]}
    vat_by_id = {r["order_id"]: r["vat"] for r in body["rows"]}
    assert abs(vat_by_id[1] - 2.1) < 1e-6

    # DRAFT config previews an UNSAVED edit (filter to NL) — must not persist.
    draft = await admin.post(
        f"/api/v1/projects/rpp1/recipes/{recipe_id}/preview",
        json={
            "config": {
                "steps": [
                    {"op": "formula", "column": "vat", "expression": 'col("amount") * 0.21'},
                    {"op": "filter", "expression": 'col("region") == "NL"'},
                ]
            },
            "limit": 50,
        },
    )
    assert draft.status_code == 200, draft.text
    assert {r["order_id"] for r in draft.json()["rows"]} == {1, 3}

    # the saved recipe config is unchanged, and nothing was written to the output
    saved = await admin.get(f"/api/v1/projects/rpp1/recipes/{recipe_id}")
    assert len(saved.json()["config"]["steps"]) == 1
    built = (
        await db_session.execute(
            text(
                "SELECT current_version FROM datasets d JOIN projects p ON p.id=d.project_id "
                "WHERE p.key='rpp1' AND d.name='enriched'"
            )
        )
    ).scalar_one()
    assert built == 0  # preview never builds


async def test_python_recipe_has_no_preview(duck_extensions: None, login_as: LoginAs) -> None:
    admin = await login_as("rp-admin2", "rp-admin2@osaip.dev")
    await _dataset_from_upload(admin, "rpp2", "orders")
    recipe = await admin.post(
        "/api/v1/projects/rpp2/recipes",
        json={
            "name": "pyr",
            "kind": "python",
            "config": {"code": "import osaip\n"},
            "input_dataset_names": ["orders"],
            "output_names": ["pyout"],
        },
    )
    assert recipe.status_code == 201, recipe.text
    preview = await admin.post(
        f"/api/v1/projects/rpp2/recipes/{recipe.json()['id']}/preview", json={}
    )
    assert preview.status_code == 422
    assert preview.json()["type"] == "urn:osaip:problem:preview-unavailable"
