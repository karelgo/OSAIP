"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from osaip_api.config import Settings, get_settings
from osaip_api.db import make_engine, make_sessionmaker
from osaip_api.middleware import register_middleware
from osaip_api.problem import register_problem_handlers
from osaip_api.routers import health, well_known


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="OSAIP API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/v1/docs" if settings.dev else None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.settings = settings

    register_problem_handlers(app)
    register_middleware(app)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(well_known.router)
    return app
