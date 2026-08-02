"""Mesh test fixtures: the shared testcontainer DB (migrated by Alembic) + a mesh app
with lifespan managed, plus a client that carries the service token."""

import os
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

from osaip_api.models import LlmConnection, Project, User
from osaip_mesh.app import create_mesh_app
from osaip_mesh.config import MeshSettings
from osaip_shared.ids import new_id

# This tests dir is deliberately NOT a package (two `tests.conftest` modules would
# collide with apps/api/tests). That also means sibling helper modules are not
# importable by default, so put this directory on the path for `openai_stub`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

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


# Builders live here rather than in a test module so every spec shares them without
# cross-importing test files (the tests dir is deliberately not a package).
MakeProject = Callable[[], Awaitable[Project]]
MakeConnection = Callable[..., Awaitable[LlmConnection]]


@pytest.fixture
def make_project(mesh_session: AsyncSession) -> MakeProject:
    async def _make() -> Project:
        project = Project(
            id=new_id(), key=f"m{uuid.uuid4().hex[:8]}", name="mesh", storage_prefix="p"
        )
        mesh_session.add(project)
        await mesh_session.flush()
        return project

    return _make


@pytest.fixture
def make_user(mesh_session: AsyncSession) -> Callable[[], Awaitable[User]]:
    async def _make() -> User:
        suffix = uuid.uuid4().hex[:8]
        user = User(
            id=new_id(),
            oidc_sub=f"sub-{suffix}",
            email=f"{suffix}@example.test",
            display_name="Mesh tester",
        )
        mesh_session.add(user)
        await mesh_session.commit()
        return user

    return _make


@pytest.fixture
def make_connection(mesh_session: AsyncSession, make_project: MakeProject) -> MakeConnection:
    async def _make(**overrides: Any) -> LlmConnection:
        project = await make_project()
        connection = LlmConnection(
            id=new_id(),
            scope="project",
            project_id=project.id,
            name=overrides.pop("name", f"echo-{uuid.uuid4().hex[:6]}"),
            provider=overrides.pop("provider", "echo"),
            base_config=overrides.pop("base_config", {}),
            allowed_models=overrides.pop("allowed_models", ["echo-1"]),
            data_residency=overrides.pop("data_residency", "local"),
            legal_basis="demo",
            purpose_codes=["demo"],
            **overrides,
        )
        mesh_session.add(connection)
        await mesh_session.commit()
        return connection

    return _make
