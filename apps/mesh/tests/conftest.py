"""Mesh test fixtures: the shared testcontainer DB (migrated by Alembic) + a mesh app
with lifespan managed, plus a client that carries the service token."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

from osaip_mesh.app import create_mesh_app
from osaip_mesh.config import MeshSettings

API_DIR = Path(__file__).resolve().parents[2] / "api"
TEST_TOKEN = "test-mesh-token"  # noqa: S105 — fixed test-only shared secret


@pytest.fixture(scope="session")
def mesh_database_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        url = container.get_connection_url()
        os.environ["OSAIP_DATABASE_URL"] = url
        try:
            command.upgrade(AlembicConfig(str(API_DIR / "alembic.ini")), "head")
            yield url
        finally:
            os.environ.pop("OSAIP_DATABASE_URL", None)


@pytest.fixture
def mesh_settings(mesh_database_url: str) -> MeshSettings:
    return MeshSettings(database_url=mesh_database_url, dev=True, mesh_service_token=TEST_TOKEN)


@pytest.fixture
async def mesh_app(mesh_settings: MeshSettings) -> AsyncIterator[FastAPI]:
    # The app authenticates against its OWN settings (app.state), so no global patching.
    application = create_mesh_app(mesh_settings)
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def mesh_client(mesh_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=mesh_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://mesh",
        headers={"X-OSAIP-Mesh-Token": TEST_TOKEN},
    ) as client:
        yield client


@pytest.fixture
async def mesh_session(mesh_app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with mesh_app.state.sessionmaker() as session:
        yield session
