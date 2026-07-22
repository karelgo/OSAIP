"""Shared fixtures: one pgvector container per test session, migrated by Alembic;
per-test app + client with a clean transactionless session."""

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

from osaip_api.app import create_app
from osaip_api.config import Settings

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
def settings(database_url: str) -> Settings:
    return Settings(database_url=database_url, dev=True)


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with LifespanManager(application):
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
