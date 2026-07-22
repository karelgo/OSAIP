import httpx


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["API-Version"] == "1.0.0"


async def test_readyz_with_db(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_404_is_problem_json_with_hint_and_docs(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "urn:osaip:problem:not-found"
    assert body["status"] == 404
    assert body["hint"]
    assert body["docs_url"].startswith("http")


async def test_security_txt(client: httpx.AsyncClient) -> None:
    response = await client.get("/.well-known/security.txt")
    assert response.status_code == 200
    assert "Contact: mailto:" in response.text
    assert "Expires: " in response.text
    assert "Policy: " in response.text
