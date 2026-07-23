"""Datasets: create-from-upload (preview-first confirm), register-from-connection
(postgres/s3/duckdb_file), sample+ETag, profile, CP-1/CP-2, injection guards,
READ_ONLY attach, and seed idempotency."""

import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import duckdb as ddb
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.config import Settings
from osaip_engine import duck
from osaip_engine.storage import Storage, StorageConfig

from .test_connections import PROBE_PASSWORD, PROBE_USER, _conn_body, _pg_parts, customer_db

_ = customer_db  # fixture re-export

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]

CSV_CONTENT = (
    b"order_id,amount,order_date,region\n"
    b"1,12.50,2024-01-15,NL\n"
    b"2,99.95,2024-01-16,BE\n"
    b"3,7.25,2024-01-17,NL\n"
)


async def _project(client: httpx.AsyncClient, key: str) -> None:
    assert (
        await client.post("/api/v1/projects", json={"key": key, "name": key})
    ).status_code == 201


async def _upload(client: httpx.AsyncClient, key: str) -> str:
    response = await client.post(
        f"/api/v1/projects/{key}/uploads",
        files={"file": ("orders.csv", CSV_CONTENT, "text/csv")},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["upload_id"])


CP2 = {"legal_basis": "Art 6(1)(e) AVG", "purpose_codes": ["analytics.internal"]}


async def test_create_from_upload_full_flow(
    duck_extensions: None, login_as: LoginAs, db_session: AsyncSession
) -> None:
    admin = await login_as("ds-admin", "ds-admin@osaip.dev")
    await _project(admin, "dsp1")
    upload_id = await _upload(admin, "dsp1")

    created = await admin.post(
        "/api/v1/projects/dsp1/datasets",
        json={
            "name": "orders",
            "source": {"kind": "upload", "upload_id": upload_id},
            "classification": "persoonsgegevens",
            "bbn_level": "bbn2",
            **CP2,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "file"
    assert body["row_count"] == 3 and body["row_count_kind"] == "exact"
    assert body["has_profile"] is True
    types = {c["name"]: c["type"] for c in body["columns"]}
    assert types["order_id"] == "BIGINT" and types["order_date"] == "DATE"
    assert body["classification"] == "persoonsgegevens" and body["bbn_level"] == "bbn2"

    # object_ref registered for ⌘K
    ref = (
        await db_session.execute(
            text("SELECT url_path FROM object_refs WHERE kind='dataset' AND name='orders'")
        )
    ).scalar_one()
    assert ref == "/p/dsp1/datasets/orders"
    # event published on the datasets topic
    event_count = (
        await db_session.execute(
            text("SELECT count(*) FROM events WHERE topic='datasets' AND type='dataset.created'")
        )
    ).scalar_one()
    assert event_count >= 1

    # sample with ETag: 304 must not touch the engine
    sample = await admin.get("/api/v1/projects/dsp1/datasets/orders/sample?limit=2")
    assert sample.status_code == 200
    assert len(sample.json()["rows"]) == 2
    etag = sample.headers["etag"]
    not_modified = await admin.get(
        "/api/v1/projects/dsp1/datasets/orders/sample?limit=2",
        headers={"if-none-match": etag},
    )
    assert not_modified.status_code == 304

    # CP-2 required: creating without purpose metadata fails
    upload_id2 = await _upload(admin, "dsp1")
    missing = await admin.post(
        "/api/v1/projects/dsp1/datasets",
        json={"name": "orders2", "source": {"kind": "upload", "upload_id": upload_id2}},
    )
    assert missing.status_code == 422
    assert "CP-2" in missing.json()["detail"]


async def test_etag_304_skips_engine(
    duck_extensions: None, login_as: LoginAs, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await login_as("ds-admin2", "ds-admin2@osaip.dev")
    await _project(admin, "dsp2")
    upload_id = await _upload(admin, "dsp2")
    await admin.post(
        "/api/v1/projects/dsp2/datasets",
        json={"name": "orders", "source": {"kind": "upload", "upload_id": upload_id}, **CP2},
    )
    first = await admin.get("/api/v1/projects/dsp2/datasets/orders/sample?limit=5")
    etag = first.headers["etag"]

    calls = {"n": 0}
    original = duck.sample_parquet

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(duck, "sample_parquet", counting)
    not_modified = await admin.get(
        "/api/v1/projects/dsp2/datasets/orders/sample?limit=5",
        headers={"if-none-match": etag},
    )
    assert not_modified.status_code == 304
    assert calls["n"] == 0  # zero engine work on 304 (plan §8)


async def test_column_classification_patch(duck_extensions: None, login_as: LoginAs) -> None:
    admin = await login_as("ds-admin3", "ds-admin3@osaip.dev")
    await _project(admin, "dsp3")
    upload_id = await _upload(admin, "dsp3")
    await admin.post(
        "/api/v1/projects/dsp3/datasets",
        json={"name": "orders", "source": {"kind": "upload", "upload_id": upload_id}, **CP2},
    )
    patched = await admin.patch(
        "/api/v1/projects/dsp3/datasets/orders",
        json={"column_classifications": {"region": "persoonsgegevens"}},
    )
    assert patched.status_code == 200
    columns = {c["name"]: c["classification"] for c in patched.json()["columns"]}
    assert columns["region"] == "persoonsgegevens"

    unknown = await admin.patch(
        "/api/v1/projects/dsp3/datasets/orders",
        json={"column_classifications": {"nope": "bsn"}},
    )
    assert unknown.status_code == 422


async def test_archive_removes_ref_and_frees_nothing_else(
    duck_extensions: None, login_as: LoginAs, db_session: AsyncSession
) -> None:
    admin = await login_as("ds-admin4", "ds-admin4@osaip.dev")
    await _project(admin, "dsp4")
    upload_id = await _upload(admin, "dsp4")
    await admin.post(
        "/api/v1/projects/dsp4/datasets",
        json={"name": "orders", "source": {"kind": "upload", "upload_id": upload_id}, **CP2},
    )
    archived = await admin.delete("/api/v1/projects/dsp4/datasets/orders")
    assert archived.status_code == 200
    refs = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM object_refs r JOIN projects p ON p.id = r.project_id "
                "WHERE r.kind='dataset' AND r.name='orders' AND p.key='dsp4'"
            )
        )
    ).scalar_one()
    assert refs == 0
    gone = await admin.get("/api/v1/projects/dsp4/datasets/orders")
    assert gone.status_code == 404


async def test_register_postgres_table(
    duck_extensions: None, login_as: LoginAs, customer_db: dict[str, Any]
) -> None:
    admin = await login_as("ds-admin5", "ds-admin5@osaip.dev")
    await _project(admin, "dsp5")
    # a table in the probe's own database
    import asyncpg

    conn = await asyncpg.connect(
        host=customer_db["host"],
        port=customer_db["port"],
        database=customer_db["database"],
        user=_pg_parts_admin()["user"],
        password=_pg_parts_admin()["password"],
    )
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS public.sales "
            "(sale_id bigint, region text, amount numeric(10,2))"
        )
        await conn.execute("GRANT SELECT ON public.sales TO " + PROBE_USER)
        count = await conn.fetchval("SELECT count(*) FROM public.sales")
        if count == 0:
            await conn.execute("INSERT INTO public.sales VALUES (1, 'NL', 10.50), (2, 'BE', 20.00)")
    finally:
        await conn.close()

    created_conn = await admin.post(
        "/api/v1/projects/dsp5/connections", json=_conn_body(customer_db)
    )
    connection_id = created_conn.json()["id"]

    # preview-first: inspect BEFORE registering (§6.3(3))
    inspected = await admin.post(
        f"/api/v1/projects/dsp5/connections/{connection_id}/inspect",
        json={"table": "public.sales"},
    )
    assert inspected.status_code == 200, inspected.text
    assert {c["name"] for c in inspected.json()["columns"]} == {"sale_id", "region", "amount"}
    assert len(inspected.json()["preview"]) == 2

    registered = await admin.post(
        "/api/v1/projects/dsp5/datasets",
        json={
            "name": "sales",
            "source": {
                "kind": "table",
                "connection_id": connection_id,
                "table": "public.sales",
            },
            # no legal_basis/purpose_codes → inherited from the connection (CP-2)
        },
    )
    assert registered.status_code == 201, registered.text
    body = registered.json()
    assert body["kind"] == "table"
    assert body["legal_basis"] == _conn_body(customer_db)["legal_basis"]  # inherited

    sample = await admin.get("/api/v1/projects/dsp5/datasets/sales/sample?limit=10")
    assert sample.status_code == 200
    assert len(sample.json()["rows"]) == 2
    assert sample.headers.get("cache-control") == "no-cache"  # external → never cached
    assert "etag" not in sample.headers

    profiled = await admin.post("/api/v1/projects/dsp5/datasets/sales/profile")
    assert profiled.status_code == 200
    assert profiled.json()["profile"]["row_count"] == 2

    # injection guard: malicious table name is rejected before any SQL
    hostile = await admin.post(
        f"/api/v1/projects/dsp5/connections/{connection_id}/inspect",
        json={"table": 'sales"; DROP TABLE x; --'},
    )
    assert hostile.status_code == 422


def _pg_parts_admin() -> dict[str, Any]:
    """Container superuser creds (owner of customer_src)."""
    import os

    url = os.environ.get("_OSAIP_TEST_PG_ADMIN", "")
    if url:
        return _pg_parts(url)
    raise RuntimeError("admin pg url not set")


@pytest.fixture(autouse=True)
def _expose_admin_pg(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("_OSAIP_TEST_PG_ADMIN", database_url)


async def test_attach_is_read_only(duck_extensions: None, customer_db: dict[str, Any]) -> None:
    """The postgres attach must reject writes (plan §6: modern postgres ext CAN write
    without READ_ONLY — this proves our attach forbids it)."""
    target = duck.PgAttach(
        host=customer_db["host"],
        port=customer_db["port"],
        database=customer_db["database"],
        user=PROBE_USER,
        password=PROBE_PASSWORD,
    )
    conn = duck._connect()
    try:
        duck._attach_postgres(conn, target, "src")
        with pytest.raises(ddb.Error, match="read-only"):
            conn.execute("CREATE TABLE src.public.hacked (i int)")
    finally:
        conn.close()


async def test_register_s3_parquet_and_duckdb_file(
    duck_extensions: None,
    login_as: LoginAs,
    seaweed_config: StorageConfig,
    settings: Settings,
) -> None:
    admin = await login_as("ds-admin6", "ds-admin6@osaip.dev")
    await _project(admin, "dsp6")
    storage = Storage(seaweed_config)

    # -- s3 parquet: write a parquet into the bucket, register via an s3 connection
    with tempfile.TemporaryDirectory() as tmp:
        parquet_path = Path(tmp) / "ext.parquet"
        conn = ddb.connect()
        conn.execute(
            f"COPY (SELECT range AS n, 'x' || range::VARCHAR AS label FROM range(10)) "
            f"TO '{parquet_path}' (FORMAT parquet)"
        )
        conn.close()
        storage.put_bytes(parquet_path.read_bytes(), "external/ext.parquet")

    s3_conn = await admin.post(
        "/api/v1/projects/dsp6/connections",
        json={
            "name": "ext-bucket",
            "kind": "s3",
            "config": {
                "endpoint": seaweed_config.endpoint,
                "bucket": seaweed_config.bucket,
                "region": "us-east-1",
                "use_ssl": False,
                "access_key": seaweed_config.access_key,
            },
            "secret": seaweed_config.secret_key,
            **CP2,
        },
    )
    s3_conn_id = s3_conn.json()["id"]
    inspected = await admin.post(
        f"/api/v1/projects/dsp6/connections/{s3_conn_id}/inspect",
        json={"path": "external/ext.parquet"},
    )
    assert inspected.status_code == 200, inspected.text
    registered = await admin.post(
        "/api/v1/projects/dsp6/datasets",
        json={
            "name": "external-parquet",
            "source": {"kind": "s3", "connection_id": s3_conn_id, "path": "external/ext.parquet"},
        },
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["row_count"] == 10

    traversal = await admin.post(
        f"/api/v1/projects/dsp6/connections/{s3_conn_id}/inspect",
        json={"path": "../secrets/ext.parquet"},
    )
    assert traversal.status_code == 422

    missing = await admin.post(
        f"/api/v1/projects/dsp6/connections/{s3_conn_id}/inspect",
        json={"path": "nope/missing.parquet"},
    )
    assert missing.status_code == 400
    assert missing.json()["type"] == "urn:osaip:problem:connection-object-not-found"

    # -- duckdb_file: a .duckdb database inside THIS project's storage prefix
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "warehouse.duckdb"
        file_conn = ddb.connect(str(db_path))
        file_conn.execute(
            "CREATE TABLE metrics AS SELECT range AS day, range * 2 AS value FROM range(7)"
        )
        file_conn.close()
        storage.put_bytes(db_path.read_bytes(), "projects/dsp6/files/warehouse.duckdb")

    duck_conn = await admin.post(
        "/api/v1/projects/dsp6/connections",
        json={
            "name": "warehouse",
            "kind": "duckdb_file",
            "config": {
                "path": f"s3://{seaweed_config.bucket}/projects/dsp6/files/warehouse.duckdb"
            },
            **CP2,
        },
    )
    assert duck_conn.status_code == 201, duck_conn.text
    duck_conn_id = duck_conn.json()["id"]
    inspected = await admin.post(
        f"/api/v1/projects/dsp6/connections/{duck_conn_id}/inspect",
        json={"table": "metrics"},
    )
    assert inspected.status_code == 200, inspected.text
    assert len(inspected.json()["preview"]) == 7

    registered = await admin.post(
        "/api/v1/projects/dsp6/datasets",
        json={
            "name": "warehouse-metrics",
            "source": {"kind": "duckdb_file", "connection_id": duck_conn_id, "table": "metrics"},
        },
    )
    assert registered.status_code == 201, registered.text
    sample = await admin.get("/api/v1/projects/dsp6/datasets/warehouse-metrics/sample")
    assert sample.status_code == 200
    assert len(sample.json()["rows"]) == 7


async def test_seed_is_idempotent_and_upgrades_phase0_db(
    duck_extensions: None,
    app: Any,
    settings: Settings,
    db_session: AsyncSession,
) -> None:
    """Seed twice over a database that already carries the Phase-0 fake object_ref —
    the real dataset must replace it via upsert, and re-runs must be no-ops."""
    from osaip_api.seed import seed

    await seed(db_session, settings)
    await db_session.commit()
    await seed(db_session, settings)  # second run: no unique violations, no dupes
    await db_session.commit()

    datasets = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM datasets d JOIN projects p ON p.id = d.project_id "
                "WHERE p.key='demo' AND d.name='sales_orders'"
            )
        )
    ).scalar_one()
    assert datasets == 1
    refs = (
        await db_session.execute(
            text("SELECT count(*) FROM object_refs WHERE kind='dataset' AND name='sales_orders'")
        )
    ).scalar_one()
    assert refs == 1
    row_count = (
        await db_session.execute(
            text(
                "SELECT v.row_count FROM dataset_versions v JOIN datasets d "
                "ON d.id = v.dataset_id WHERE d.name='sales_orders'"
            )
        )
    ).scalar_one()
    assert row_count == 60
    # demo_src exists with data (AC-2 substrate)
    import asyncpg

    parts = _pg_parts(settings.database_url)
    conn = await asyncpg.connect(
        host=parts["host"],
        port=parts["port"],
        database="demo_src",
        user=parts["user"],
        password=parts["password"],
    )
    try:
        assert await conn.fetchval("SELECT count(*) FROM sales") == 40
    finally:
        await conn.close()
