"""Application settings. All values come from OSAIP_* env vars (see infra/compose)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSAIP_", extra="ignore")

    database_url: str = "postgresql+asyncpg://osaip:osaip@localhost:5433/osaip"
    dev: bool = False
    session_secret: str = "dev-session-secret-not-for-prod"
    session_ttl_seconds: int = 8 * 60 * 60

    # OIDC (ADR-0001). issuer/authorize are browser-facing; token/JWKS go to the
    # internal base so the api container can reach Keycloak in compose.
    oidc_issuer: str = "http://localhost:8081/realms/osaip"
    oidc_internal_base: str = "http://localhost:8081/realms/osaip"
    oidc_client_id: str = "osaip-api"
    oidc_client_secret: str = "osaip-dev-secret"

    # Browser-facing origin of the app (vite in dev; used for redirects + CSRF checks)
    public_url: str = "http://localhost:5173"

    docs_base_url: str = "https://github.com/osaip/osaip/blob/main/docs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
