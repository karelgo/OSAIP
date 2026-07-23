"""Connections CRUD, RBAC, CP-2 requirements, and sanitized test-connection.

The session-scoped testcontainer Postgres doubles as the "customer database":
tests connect to it under a separate database name so the platform-DB SSRF guard
(which matches host+port+dbname exactly) does not trigger.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_engine.storage import StorageConfig

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]


def _pg_parts(database_url: str) -> dict[str, Any]:
    url = urlsplit(database_url.replace("+asyncpg", ""))
    return {
        "host": url.hostname,
        "port": url.port,
        "database": url.path.lstrip("/"),
        "user": url.username,
        "password": url.password,
    }


async def _make_project(client: httpx.AsyncClient, key: str) -> None:
    response = await client.post("/api/v1/projects", json={"key": key, "name": key})
    assert response.status_code == 201


def _conn_body(parts: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "customer-db",
        "kind": "postgres",
        "config": {
            "host": parts["host"],
            "port": parts["port"],
            "database": parts["database"],
            "user": parts["user"],
        },
        "secret": parts["password"],
        "legal_basis": "Art 6(1)(e) AVG — public task",
        "purpose_codes": ["analytics.internal"],
    }
    body.update(overrides)
    return body


# Deliberately distinctive credentials: leak assertions search response bodies for
# these strings, so they must never collide with ordinary words (the container's own
# password is literally "test", which appears in e.g. "Connection test failed").
PROBE_USER = "osaip_probe"
PROBE_PASSWORD = "Probe-Secret-9000x"  # noqa: S105


@pytest.fixture
async def customer_db(db_session: AsyncSession, database_url: str) -> dict[str, Any]:
    """A second database + login role on the test container, so the SSRF guard stays
    out of the way and leak assertions have a distinctive credential to search for."""
    import contextlib

    parts = _pg_parts(database_url)
    engine_conn = await db_session.connection()
    raw = await engine_conn.get_raw_connection()
    # CREATE DATABASE/ROLE need autocommit — use the asyncpg driver connection directly.
    driver = raw.driver_connection
    with contextlib.suppress(Exception):  # already exist on later tests in the session
        await driver.execute(f"CREATE ROLE {PROBE_USER} LOGIN PASSWORD '{PROBE_PASSWORD}'")
    with contextlib.suppress(Exception):
        await driver.execute("CREATE DATABASE customer_src")
    await db_session.rollback()
    return {**parts, "database": "customer_src", "user": PROBE_USER, "password": PROBE_PASSWORD}


async def test_admin_creates_and_lists_connection(
    login_as: LoginAs, customer_db: dict[str, Any]
) -> None:
    admin = await login_as("sub-conn-admin", "conn-admin@osaip.dev")
    await _make_project(admin, "connp1")
    created = await admin.post("/api/v1/projects/connp1/connections", json=_conn_body(customer_db))
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["has_secret"] is True
    assert "secret" not in payload
    assert customer_db["password"] not in created.text

    listed = await admin.get("/api/v1/projects/connp1/connections")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["name"] == "customer-db"
    assert customer_db["password"] not in listed.text


async def test_editor_and_viewer_cannot_manage_connections(
    login_as: LoginAs, customer_db: dict[str, Any]
) -> None:
    admin = await login_as("sub-conn-admin2", "conn-admin2@osaip.dev")
    await _make_project(admin, "connp2")
    members = [
        {"email": "conn-admin2@osaip.dev", "role": "admin"},
        {"email": "conn-editor@osaip.dev", "role": "editor"},
        {"email": "conn-viewer@osaip.dev", "role": "viewer"},
    ]
    editor = await login_as("sub-conn-editor", "conn-editor@osaip.dev")
    viewer = await login_as("sub-conn-viewer", "conn-viewer@osaip.dev")
    assert (
        await admin.put("/api/v1/projects/connp2/members", json={"members": members})
    ).status_code == 200

    for client in (editor, viewer):
        response = await client.post(
            "/api/v1/projects/connp2/connections", json=_conn_body(customer_db)
        )
        assert response.status_code == 403
        assert response.json()["type"] == "urn:osaip:problem:forbidden"
    # capability flag drives the UI (§6.6)
    project = (await admin.get("/api/v1/projects/connp2")).json()
    assert project["capabilities"]["can_manage_connections"] is True
    project_as_editor = (await editor.get("/api/v1/projects/connp2")).json()
    assert project_as_editor["capabilities"]["can_manage_connections"] is False


async def test_cp2_fields_required(login_as: LoginAs, customer_db: dict[str, Any]) -> None:
    admin = await login_as("sub-conn-admin3", "conn-admin3@osaip.dev")
    await _make_project(admin, "connp3")
    body = _conn_body(customer_db)
    del body["legal_basis"]
    response = await admin.post("/api/v1/projects/connp3/connections", json=body)
    assert response.status_code == 422

    body = _conn_body(customer_db, purpose_codes=[])
    response = await admin.post("/api/v1/projects/connp3/connections", json=body)
    assert response.status_code == 422


async def test_test_connection_ok_and_bad_creds_sanitized(
    login_as: LoginAs, customer_db: dict[str, Any]
) -> None:
    admin = await login_as("sub-conn-admin4", "conn-admin4@osaip.dev")
    await _make_project(admin, "connp4")
    created = await admin.post("/api/v1/projects/connp4/connections", json=_conn_body(customer_db))
    connection_id = created.json()["id"]
    ok = await admin.post(f"/api/v1/projects/connp4/connections/{connection_id}/test")
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"] is True and ok.json()["latency_ms"] > 0

    # Wrong password → clean problem+json; body leaks neither password nor DSN (AC-3).
    patched = await admin.patch(
        f"/api/v1/projects/connp4/connections/{connection_id}", json={"secret": "wrong-pass"}
    )
    assert patched.status_code == 200
    bad = await admin.post(f"/api/v1/projects/connp4/connections/{connection_id}/test")
    assert bad.status_code == 400
    problem = bad.json()
    assert problem["type"] == "urn:osaip:problem:connection-auth-failed"
    for never_leaked in ("wrong-pass", customer_db["password"], "postgresql://"):
        assert never_leaked not in bad.text
    assert problem["hint"]


async def test_test_connection_host_unreachable(
    login_as: LoginAs, customer_db: dict[str, Any]
) -> None:
    admin = await login_as("sub-conn-admin5", "conn-admin5@osaip.dev")
    await _make_project(admin, "connp5")
    body = _conn_body(customer_db)
    body["config"]["port"] = 1  # nothing listens there
    created = await admin.post("/api/v1/projects/connp5/connections", json=body)
    bad = await admin.post(f"/api/v1/projects/connp5/connections/{created.json()['id']}/test")
    assert bad.status_code == 400
    assert bad.json()["type"] == "urn:osaip:problem:connection-unreachable"


async def test_platform_db_is_denied(login_as: LoginAs, database_url: str) -> None:
    admin = await login_as("sub-conn-admin6", "conn-admin6@osaip.dev")
    await _make_project(admin, "connp6")
    body = _conn_body(_pg_parts(database_url))  # exactly the metadata DB
    response = await admin.post("/api/v1/projects/connp6/connections", json=body)
    assert response.status_code == 422
    assert response.json()["type"] == "urn:osaip:problem:target-not-allowed"


async def test_invalid_host_rejected(login_as: LoginAs, customer_db: dict[str, Any]) -> None:
    admin = await login_as("sub-conn-admin7", "conn-admin7@osaip.dev")
    await _make_project(admin, "connp7")
    body = _conn_body(customer_db)
    body["config"]["host"] = "bad host'; --"
    response = await admin.post("/api/v1/projects/connp7/connections", json=body)
    assert response.status_code == 422


async def test_audit_rows_written(
    login_as: LoginAs, customer_db: dict[str, Any], db_session: AsyncSession
) -> None:
    admin = await login_as("sub-conn-admin8", "conn-admin8@osaip.dev")
    await _make_project(admin, "connp8")
    created = await admin.post("/api/v1/projects/connp8/connections", json=_conn_body(customer_db))
    connection_id = created.json()["id"]
    await admin.patch(
        f"/api/v1/projects/connp8/connections/{connection_id}", json={"name": "renamed"}
    )
    actions = (
        (
            await db_session.execute(
                text(
                    "SELECT action FROM audit_log WHERE object_kind = 'connection' "
                    "AND object_id = :oid ORDER BY seq"
                ),
                {"oid": connection_id},
            )
        )
        .scalars()
        .all()
    )
    assert actions == ["connection.created", "connection.updated"]
    # secret values never reach audit details
    details = (
        (
            await db_session.execute(
                text(
                    "SELECT details::text FROM audit_log WHERE object_kind = 'connection' "
                    "AND object_id = :oid"
                ),
                {"oid": connection_id},
            )
        )
        .scalars()
        .all()
    )
    assert all(customer_db["password"] not in row for row in details)


async def test_s3_connection_test_ok_and_bad_creds_sanitized(
    login_as: LoginAs, seaweed_config: "StorageConfig"
) -> None:
    admin = await login_as("sub-conn-admin10", "conn-admin10@osaip.dev")
    await _make_project(admin, "connp10")
    body = {
        "name": "object-store",
        "kind": "s3",
        "config": {
            "endpoint": seaweed_config.endpoint,
            "bucket": seaweed_config.bucket,
            "region": "us-east-1",
            "use_ssl": False,
            "access_key": seaweed_config.access_key,
        },
        "secret": seaweed_config.secret_key,
        "legal_basis": "Art 6(1)(e) AVG — public task",
        "purpose_codes": ["analytics.internal"],
    }
    created = await admin.post("/api/v1/projects/connp10/connections", json=body)
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]
    ok = await admin.post(f"/api/v1/projects/connp10/connections/{connection_id}/test")
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"] is True

    await admin.patch(
        f"/api/v1/projects/connp10/connections/{connection_id}",
        json={"secret": "Wrong-S3-Secret-123"},
    )
    bad = await admin.post(f"/api/v1/projects/connp10/connections/{connection_id}/test")
    assert bad.status_code == 400, bad.text
    assert bad.json()["type"] == "urn:osaip:problem:connection-auth-failed"
    for never_leaked in ("Wrong-S3-Secret-123", seaweed_config.secret_key):
        assert never_leaked not in bad.text


async def test_archive_blocked_when_in_use_then_ok(
    login_as: LoginAs, customer_db: dict[str, Any], db_session: AsyncSession
) -> None:
    admin = await login_as("sub-conn-admin9", "conn-admin9@osaip.dev")
    await _make_project(admin, "connp9")
    created = await admin.post("/api/v1/projects/connp9/connections", json=_conn_body(customer_db))
    connection_id = created.json()["id"]
    # Fake an active dataset referencing it (datasets API arrives next slice).
    await db_session.execute(
        text(
            "INSERT INTO datasets (id, project_id, name, kind, connection_id, description, "
            "classification, legal_basis, purpose_codes, params, status, current_version) "
            "SELECT gen_random_uuid(), p.id, 'dep', 'table', :cid, '', 'none', 'basis', "
            "ARRAY['analytics.internal'], '{}'::jsonb, 'active', 0 FROM projects p "
            "WHERE p.key = 'connp9'"
        ),
        {"cid": connection_id},
    )
    await db_session.commit()
    blocked = await admin.delete(f"/api/v1/projects/connp9/connections/{connection_id}")
    assert blocked.status_code == 409
    await db_session.execute(text("UPDATE datasets SET status = 'archived' WHERE name = 'dep'"))
    await db_session.commit()
    archived = await admin.delete(f"/api/v1/projects/connp9/connections/{connection_id}")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
