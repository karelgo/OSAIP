import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import Session as SessionRow
from osaip_api.models import User

from .fake_idp import FakeIdp

REPO_ROOT = Path(__file__).resolve().parents[3]


async def _login(client: httpx.AsyncClient, next_path: str = "/") -> httpx.Response:
    """Run the full login dance against the fake IdP; returns the callback response."""
    start = await client.get(f"/api/v1/auth/login?next={next_path}")
    assert start.status_code == 302
    authorize = urlsplit(start.headers["location"])
    params = parse_qs(authorize.query)
    assert params["code_challenge_method"] == ["S256"]
    state = params["state"][0]
    nonce = params["nonce"][0]
    # The fake IdP signs the id_token with nonce=code (see fake_idp.py).
    return await client.get(f"/api/v1/auth/callback?code={nonce}&state={state}")


async def test_login_redirects_to_idp_with_pkce(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/login")
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://localhost:8081/realms/osaip/protocol/openid-connect/auth")
    params = parse_qs(urlsplit(location).query)
    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    assert "state" in params and "nonce" in params


async def test_login_rejects_absolute_next(client: httpx.AsyncClient) -> None:
    for bad in ("https://evil.example", "//evil.example", "http://x", "javascript:alert(1)"):
        response = await client.get("/api/v1/auth/login", params={"next": bad})
        assert response.status_code == 400, bad
        assert response.json()["type"] == "urn:osaip:problem:invalid-redirect"


async def test_callback_provisions_user_and_sets_session(
    client: httpx.AsyncClient, db_session: AsyncSession, fake_idp: FakeIdp
) -> None:
    response = await _login(client, next_path="/p/demo")
    assert response.status_code == 302
    assert response.headers["location"] == "/p/demo"
    set_cookie = response.headers["set-cookie"]
    assert "osaip_session=" in set_cookie
    assert "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie.replace("Lax", "lax")

    user = (
        await db_session.execute(select(User).where(User.oidc_sub == fake_idp.subject))
    ).scalar_one()
    assert user.email == "admin@osaip.dev"
    assert user.last_login_at is not None

    row = (
        (await db_session.execute(select(SessionRow).where(SessionRow.user_id == user.id)))
        .scalars()
        .first()
    )
    assert row is not None
    assert row.oidc_sid == fake_idp.sid
    # Raw token is never stored — only its hash (64 hex chars, not the cookie value).
    assert len(row.token_hash) == 64

    logins = (
        await db_session.execute(text("SELECT count(*) FROM audit_log WHERE action = 'auth.login'"))
    ).scalar_one()
    assert logins >= 1


async def test_callback_rejects_state_mismatch(client: httpx.AsyncClient) -> None:
    start = await client.get("/api/v1/auth/login")
    nonce = parse_qs(urlsplit(start.headers["location"]).query)["nonce"][0]
    response = await client.get(f"/api/v1/auth/callback?code={nonce}&state=wrong")
    assert response.status_code == 400
    assert response.json()["type"] == "urn:osaip:problem:oidc-state-mismatch"


async def test_me_requires_and_returns_session_user(client: httpx.AsyncClient) -> None:
    unauthenticated = await client.get("/api/v1/me")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["type"] == "urn:osaip:problem:unauthenticated"

    await _login(client)
    me = await client.get("/api/v1/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "admin@osaip.dev"
    assert body["prefs"]["theme"] == "system"


async def test_prefs_patch_roundtrip(client: httpx.AsyncClient) -> None:
    await _login(client)
    patched = await client.patch("/api/v1/me/prefs", json={"theme": "dark"})
    assert patched.status_code == 200
    assert patched.json()["theme"] == "dark"
    assert (await client.get("/api/v1/me")).json()["prefs"]["theme"] == "dark"


async def test_logout_kills_session_and_returns_idp_url(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login(client)
    before = (await db_session.execute(select(func.count(SessionRow.id)))).scalar_one()
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    logout_url = response.json()["logout_url"]
    assert logout_url.startswith(
        "http://localhost:8081/realms/osaip/protocol/openid-connect/logout"
    )
    assert "id_token_hint=" in logout_url
    after = (await db_session.execute(select(func.count(SessionRow.id)))).scalar_one()
    assert after == before - 1
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_csrf_blocks_cross_site_mutations(client: httpx.AsyncClient) -> None:
    await _login(client)
    blocked = await client.post("/api/v1/auth/logout", headers={"Sec-Fetch-Site": "cross-site"})
    assert blocked.status_code == 403
    assert blocked.json()["type"] == "urn:osaip:problem:csrf"

    blocked_origin = await client.post(
        "/api/v1/auth/logout", headers={"Origin": "https://evil.example"}
    )
    assert blocked_origin.status_code == 403

    allowed = await client.post("/api/v1/auth/logout", headers={"Sec-Fetch-Site": "same-origin"})
    assert allowed.status_code == 200


async def test_realm_export_matches_nlgov_profile_settings() -> None:
    """CP-14: the committed realm preset is asserted so drift fails CI (ADR-0005)."""
    realm = json.loads((REPO_ROOT / "infra/compose/keycloak/realm-osaip.json").read_text())
    client_def = next(c for c in realm["clients"] if c["clientId"] == "osaip-api")
    assert client_def["publicClient"] is False
    assert client_def["standardFlowEnabled"] is True
    assert client_def["implicitFlowEnabled"] is False
    assert client_def["directAccessGrantsEnabled"] is False
    assert client_def["attributes"]["pkce.code.challenge.method"] == "S256"
    for uri in client_def["redirectUris"]:
        assert uri.endswith("/api/v1/auth/callback"), "exact redirect URIs only"
    assert realm["defaultSignatureAlgorithm"] == "RS256"
    assert realm["accessTokenLifespan"] <= 300
