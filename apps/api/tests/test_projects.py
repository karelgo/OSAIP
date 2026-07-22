import secrets
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]


def _key() -> str:
    return f"proj-{secrets.token_hex(4)}"


async def _create(client: httpx.AsyncClient, key: str, **overrides: str) -> httpx.Response:
    body = {"key": key, "name": f"Project {key}", "description": "test project"}
    body.update(overrides)
    return await client.post("/api/v1/projects", json=body)


async def test_create_project_full_shape(login_as: LoginAs, db_session: AsyncSession) -> None:
    client = await login_as("owner-1", "owner1@osaip.dev")
    key = _key()
    response = await _create(client, key)
    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "admin"
    assert body["capabilities"] == {
        "can_edit": True,
        "can_manage_members": True,
        "can_archive": True,
    }

    audit = (
        await db_session.execute(
            text("SELECT count(*) FROM audit_log WHERE action='project.created' AND object_id=:k"),
            {"k": key},
        )
    ).scalar_one()
    assert audit == 1
    refs = (
        await db_session.execute(
            text("SELECT count(*) FROM object_refs WHERE kind='project' AND url_path=:p"),
            {"p": f"/p/{key}"},
        )
    ).scalar_one()
    assert refs == 1


async def test_duplicate_key_conflicts(login_as: LoginAs) -> None:
    client = await login_as("owner-2", "owner2@osaip.dev")
    key = _key()
    assert (await _create(client, key)).status_code == 201
    duplicate = await _create(client, key)
    assert duplicate.status_code == 409
    assert duplicate.json()["type"] == "urn:osaip:problem:project-key-taken"


async def test_idempotency_replay_and_reuse_conflict(
    login_as: LoginAs, db_session: AsyncSession
) -> None:
    client = await login_as("owner-3", "owner3@osaip.dev")
    key = _key()
    idem = {"Idempotency-Key": secrets.token_hex(8)}
    first = await client.post(
        "/api/v1/projects",
        json={"key": key, "name": "Idem", "description": ""},
        headers=idem,
    )
    assert first.status_code == 201
    replay = await client.post(
        "/api/v1/projects",
        json={"key": key, "name": "Idem", "description": ""},
        headers=idem,
    )
    assert replay.status_code == 201
    assert replay.json() == first.json()
    count = (
        await db_session.execute(text("SELECT count(*) FROM projects WHERE key=:k"), {"k": key})
    ).scalar_one()
    assert count == 1

    reused = await client.post(
        "/api/v1/projects",
        json={"key": _key(), "name": "Different", "description": ""},
        headers=idem,
    )
    assert reused.status_code == 422
    assert reused.json()["type"] == "urn:osaip:problem:idempotency-key-reuse"


async def test_visibility_membership_and_roles(login_as: LoginAs) -> None:
    owner = await login_as("owner-4", "owner4@osaip.dev")
    other = await login_as("other-4", "other4@osaip.dev")
    key = _key()
    assert (await _create(owner, key)).status_code == 201

    # Non-member: invisible in list, 404 on detail (existence not leaked)
    listing = (await other.get("/api/v1/projects")).json()
    assert all(item["key"] != key for item in listing["items"])
    assert (await other.get(f"/api/v1/projects/{key}")).status_code == 404

    # Add as viewer → visible, read-only capabilities, PATCH forbidden (403)
    put = await owner.put(
        f"/api/v1/projects/{key}/members",
        json={
            "members": [
                {"email": "owner4@osaip.dev", "role": "admin"},
                {"email": "other4@osaip.dev", "role": "viewer"},
            ]
        },
    )
    assert put.status_code == 200
    detail = (await other.get(f"/api/v1/projects/{key}")).json()
    assert detail["role"] == "viewer"
    assert detail["capabilities"]["can_edit"] is False
    patch = await other.patch(f"/api/v1/projects/{key}", json={"name": "Nope"})
    assert patch.status_code == 403
    assert patch.json()["type"] == "urn:osaip:problem:forbidden"


async def test_site_admin_sees_everything(login_as: LoginAs, db_session: AsyncSession) -> None:
    owner = await login_as("owner-5", "owner5@osaip.dev")
    key = _key()
    assert (await _create(owner, key)).status_code == 201

    admin = await login_as("site-admin-1", "siteadmin@osaip.dev")
    await db_session.execute(
        text("UPDATE users SET is_site_admin=true WHERE oidc_sub='site-admin-1'")
    )
    await db_session.commit()
    detail = await admin.get(f"/api/v1/projects/{key}")
    assert detail.status_code == 200
    assert detail.json()["role"] == "admin"


async def test_etag_304(login_as: LoginAs) -> None:
    client = await login_as("owner-6", "owner6@osaip.dev")
    key = _key()
    assert (await _create(client, key)).status_code == 201
    first = await client.get(f"/api/v1/projects/{key}")
    etag = first.headers["etag"]
    assert etag.startswith('W/"')
    cached = await client.get(f"/api/v1/projects/{key}", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    changed = await client.patch(f"/api/v1/projects/{key}", json={"name": "Renamed"})
    assert changed.status_code == 200
    fresh = await client.get(f"/api/v1/projects/{key}", headers={"If-None-Match": etag})
    assert fresh.status_code == 200


async def test_pagination_cursor(login_as: LoginAs) -> None:
    client = await login_as("owner-7", "owner7@osaip.dev")
    keys = sorted(_key() for _ in range(3))
    for key in keys:
        assert (await _create(client, key)).status_code == 201
    page1 = (await client.get("/api/v1/projects", params={"limit": 2})).json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"]
    page2 = (
        await client.get("/api/v1/projects", params={"limit": 2, "cursor": page1["next_cursor"]})
    ).json()
    page1_keys = {item["key"] for item in page1["items"]}
    page2_keys = {item["key"] for item in page2["items"]}
    assert not page1_keys & page2_keys
    assert set(keys) <= page1_keys | page2_keys


async def test_members_rules(login_as: LoginAs) -> None:
    owner = await login_as("owner-8", "owner8@osaip.dev")
    await login_as("member-8", "member8@osaip.dev")  # provisions the user
    key = _key()
    assert (await _create(owner, key)).status_code == 201

    no_admin = await owner.put(
        f"/api/v1/projects/{key}/members",
        json={"members": [{"email": "member8@osaip.dev", "role": "viewer"}]},
    )
    assert no_admin.status_code == 409
    assert no_admin.json()["type"] == "urn:osaip:problem:last-admin"

    unknown = await owner.put(
        f"/api/v1/projects/{key}/members",
        json={
            "members": [
                {"email": "owner8@osaip.dev", "role": "admin"},
                {"email": "ghost@osaip.dev", "role": "viewer"},
            ]
        },
    )
    assert unknown.status_code == 422
    assert unknown.json()["type"] == "urn:osaip:problem:unknown-user"

    ok = await owner.put(
        f"/api/v1/projects/{key}/members",
        json={
            "members": [
                {"email": "owner8@osaip.dev", "role": "admin"},
                {"email": "member8@osaip.dev", "role": "editor"},
            ]
        },
    )
    assert ok.status_code == 200
    emails = {item["email"]: item["role"] for item in ok.json()["items"]}
    assert emails == {"owner8@osaip.dev": "admin", "member8@osaip.dev": "editor"}

    owner_id = next(
        item["user_id"] for item in ok.json()["items"] if item["email"] == "owner8@osaip.dev"
    )
    last_admin = await owner.delete(f"/api/v1/projects/{key}/members/{owner_id}")
    assert last_admin.status_code == 409


async def test_archive_makes_project_read_only(login_as: LoginAs, db_session: AsyncSession) -> None:
    owner = await login_as("owner-9", "owner9@osaip.dev")
    key = _key()
    assert (await _create(owner, key)).status_code == 201
    archived = await owner.delete(f"/api/v1/projects/{key}")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["capabilities"]["can_edit"] is False

    blocked = await owner.patch(f"/api/v1/projects/{key}", json={"name": "Nope"})
    assert blocked.status_code == 409
    assert blocked.json()["type"] == "urn:osaip:problem:project-archived"

    refs = (
        await db_session.execute(
            text("SELECT count(*) FROM object_refs WHERE url_path=:p"), {"p": f"/p/{key}"}
        )
    ).scalar_one()
    assert refs == 0


async def test_project_audit_listing(login_as: LoginAs) -> None:
    owner = await login_as("owner-10", "owner10@osaip.dev")
    key = _key()
    assert (await _create(owner, key)).status_code == 201
    assert (await owner.patch(f"/api/v1/projects/{key}", json={"name": "V2"})).status_code == 200
    audit = (await owner.get(f"/api/v1/projects/{key}/audit")).json()
    actions = [item["action"] for item in audit["items"]]
    assert "project.created" in actions and "project.updated" in actions


async def test_site_audit_and_verify_require_site_admin(
    login_as: LoginAs, db_session: AsyncSession
) -> None:
    normal = await login_as("normal-11", "normal11@osaip.dev")
    assert (await normal.get("/api/v1/audit")).status_code == 403
    assert (await normal.post("/api/v1/audit/verify")).status_code == 403

    admin = await login_as("site-admin-2", "siteadmin2@osaip.dev")
    await db_session.execute(
        text("UPDATE users SET is_site_admin=true WHERE oidc_sub='site-admin-2'")
    )
    await db_session.commit()
    listing = await admin.get("/api/v1/audit")
    assert listing.status_code == 200
    assert listing.json()["items"]
    verify = await admin.post("/api/v1/audit/verify")
    assert verify.status_code == 200
    assert verify.json()["ok"] is True
