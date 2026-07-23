"""Application settings. All values come from OSAIP_* env vars (see infra/compose)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSAIP_", extra="ignore")

    database_url: str = "postgresql+asyncpg://osaip:osaip@localhost:5433/osaip"
    dev: bool = False
    session_secret: str = "dev-session-secret-not-for-prod"
    session_ttl_seconds: int = 8 * 60 * 60
    # MultiFernet key list (ADR-0006); dev-only default, replace in prod.
    secret_key: str = "b3NhaXAtZGV2LW9ubHktc2VjcmV0LWtleS0zMmJ5dGU="

    # OIDC (ADR-0001). issuer/authorize are browser-facing; token/JWKS go to the
    # internal base so the api container can reach Keycloak in compose.
    oidc_issuer: str = "http://localhost:8081/realms/osaip"
    oidc_internal_base: str = "http://localhost:8081/realms/osaip"
    oidc_client_id: str = "osaip-api"
    oidc_client_secret: str = "osaip-dev-secret"

    # Browser-facing origin of the app (vite in dev; used for redirects + CSRF checks)
    public_url: str = "http://localhost:5173"

    docs_base_url: str = "https://github.com/osaip/osaip/blob/main/docs"

    # Object storage (ADR-0006 §2). Host-run tools default to the published dev port;
    # compose overrides the endpoint to seaweedfs:8333 (dual-hostname, like OIDC).
    s3_endpoint: str = "localhost:8333"  # host:port, scheme-less
    s3_bucket: str = "osaip"
    s3_access_key: str = "osaipdev"
    s3_secret_key: str = "osaip-dev-s3-secret"
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = False

    # Upload caps (plan §6): absolute cap enforced by middleware, xlsx cap in-handler.
    upload_max_bytes: int = 100 * 1024 * 1024
    upload_max_bytes_xlsx: int = 25 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
