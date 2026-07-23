"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from osaip_api.auth.oidc import OidcClient
from osaip_api.config import Settings, get_settings
from osaip_api.db import make_engine, make_sessionmaker
from osaip_api.events import EventBroker, asyncpg_dsn
from osaip_api.middleware import register_middleware
from osaip_api.problem import register_problem_handlers
from osaip_api.routers import (
    audit_admin,
    auth,
    connections,
    dev,
    events,
    health,
    me,
    notifications,
    projects,
    search,
    well_known,
)
from osaip_api.secrets import Vault


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        oidc_http = httpx.AsyncClient(timeout=10.0)
        broker = EventBroker(asyncpg_dsn(settings.database_url))
        await broker.start()
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.oidc = OidcClient(settings, oidc_http)
        app.state.event_broker = broker
        try:
            yield
        finally:
            await broker.stop()
            await oidc_http.aclose()
            await engine.dispose()

    app = FastAPI(
        title="OSAIP API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/v1/docs" if settings.dev else None,
        openapi_url="/api/v1/openapi.json",
        # Route function names become operation ids → clean generated client names
        # (getMe, listProjects) instead of path-mangled ones.
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.settings = settings
    # Fails fast on a malformed OSAIP_SECRET_KEY (ADR-0006 §1) — boot, not first write.
    app.state.vault = Vault(settings.secret_key)

    register_problem_handlers(app)
    register_middleware(app)
    # Transient cookie for the OIDC login dance ONLY (state/nonce/PKCE verifier);
    # auth sessions live server-side (ADR-0001).
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="osaip_oidc",
        max_age=600,
        same_site="lax",
        https_only=not settings.dev,
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(me.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(connections.router, prefix="/api/v1")
    app.include_router(audit_admin.router, prefix="/api/v1")
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    if settings.dev:
        app.include_router(dev.router, prefix="/api/v1")
    app.include_router(well_known.router)
    return app
