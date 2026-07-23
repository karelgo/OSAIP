"""Shared fixtures: one pgvector container per test session, migrated by Alembic;
per-test app + client with a clean transactionless session."""

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import uvicorn
from alembic import command
from alembic.config import Config as AlembicConfig
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

from osaip_api.app import create_app
from osaip_api.auth.oidc import OidcClient
from osaip_api.config import Settings
from osaip_engine.storage import StorageConfig

from .fake_idp import FakeIdp

API_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        url = container.get_connection_url()
        alembic_cfg = AlembicConfig(str(API_DIR / "alembic.ini"))
        os.environ["OSAIP_DATABASE_URL"] = url
        try:
            command.upgrade(alembic_cfg, "head")
            yield url
        finally:
            os.environ.pop("OSAIP_DATABASE_URL", None)


@pytest.fixture
def settings(database_url: str, seaweed_config: "StorageConfig") -> Settings:
    return Settings(
        database_url=database_url,
        dev=True,
        s3_endpoint=seaweed_config.endpoint,
        s3_bucket=seaweed_config.bucket,
        s3_access_key=seaweed_config.access_key,
        s3_secret_key=seaweed_config.secret_key,
        # Small caps so size-limit tests don't push real 100 MB bodies around.
        upload_max_bytes=1024 * 1024,
        upload_max_bytes_xlsx=64 * 1024,
    )


@pytest.fixture
def fake_idp(settings: Settings) -> "FakeIdp":
    return FakeIdp(settings)


@pytest.fixture
async def app(settings: Settings, fake_idp: "FakeIdp") -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with LifespanManager(application):
        # Point the OIDC client at the in-process fake IdP (tests never do real HTTP).
        application.state.oidc = OidcClient(settings, fake_idp.make_client())
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
async def db_session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with app.state.sessionmaker() as session:
        yield session


@pytest.fixture
async def login_as(
    app: FastAPI, fake_idp: FakeIdp
) -> AsyncIterator[Callable[..., Awaitable[httpx.AsyncClient]]]:
    """Factory: a fresh signed-in client for any identity (fresh cookie jar per call)."""
    opened: list[httpx.AsyncClient] = []

    async def _login_as(subject: str, email: str, name: str = "Test User") -> httpx.AsyncClient:
        fake_idp.subject, fake_idp.email, fake_idp.name = subject, email, name
        new_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )
        opened.append(new_client)
        start = await new_client.get("/api/v1/auth/login")
        assert start.status_code == 302
        params = parse_qs(urlsplit(start.headers["location"]).query)
        callback = await new_client.get(
            f"/api/v1/auth/callback?code={params['nonce'][0]}&state={params['state'][0]}"
        )
        assert callback.status_code == 302
        return new_client

    yield _login_as
    for opened_client in opened:
        await opened_client.aclose()


@pytest.fixture
async def http_base_url(app: FastAPI) -> AsyncIterator[str]:
    """Real uvicorn server on an ephemeral port — required for SSE tests, because
    httpx's ASGITransport buffers the whole response and never yields a live stream."""
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        lifespan="off",
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 — uvicorn exposes no readiness event
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


@pytest.fixture
async def login_as_http(
    http_base_url: str, fake_idp: FakeIdp
) -> AsyncIterator[Callable[..., Awaitable[httpx.AsyncClient]]]:
    """Like login_as, but over real HTTP (streams work)."""
    opened: list[httpx.AsyncClient] = []

    async def _login_as(subject: str, email: str, name: str = "Test User") -> httpx.AsyncClient:
        fake_idp.subject, fake_idp.email, fake_idp.name = subject, email, name
        new_client = httpx.AsyncClient(base_url=http_base_url)
        opened.append(new_client)
        start = await new_client.get("/api/v1/auth/login")
        assert start.status_code == 302
        params = parse_qs(urlsplit(start.headers["location"]).query)
        callback = await new_client.get(
            f"/api/v1/auth/callback?code={params['nonce'][0]}&state={params['state'][0]}"
        )
        assert callback.status_code == 302
        return new_client

    yield _login_as
    for opened_client in opened:
        await opened_client.aclose()
