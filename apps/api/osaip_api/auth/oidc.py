"""OIDC relying-party plumbing (ADR-0001).

Discovery and all backchannel calls (token, JWKS) go to `oidc_internal_base` so the
api container can reach the IdP inside compose; the authorization endpoint the browser
is sent to comes from the discovery document, which the IdP pins to the browser-facing
hostname. The `iss` claim MUST equal the configured browser-facing issuer.

Uses authlib.jose for JWKS/JWT validation; the code+PKCE exchange itself is a plain
httpx POST (the Starlette OAuth client is deliberately avoided — it would store tokens
in a readable cookie, see ADR-0001).
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

import httpx
from authlib.jose import JsonWebKey, JsonWebToken

from osaip_api.config import Settings
from osaip_api.problem import Problem

_jwt = JsonWebToken(["RS256", "PS256"])


@dataclass
class OidcMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None


class OidcClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http
        self._metadata: OidcMetadata | None = None
        self._jwks: Any = None

    async def metadata(self) -> OidcMetadata:
        if self._metadata is None:
            url = f"{self._settings.oidc_internal_base}/.well-known/openid-configuration"
            response = await self._http.get(url)
            response.raise_for_status()
            doc = response.json()
            if doc["issuer"] != self._settings.oidc_issuer:
                raise Problem(
                    502,
                    title="OIDC issuer mismatch",
                    detail=(
                        f"The identity provider reports issuer {doc['issuer']!r} but this "
                        f"deployment expects {self._settings.oidc_issuer!r}."
                    ),
                    hint="Check OSAIP_OIDC_ISSUER and the IdP hostname configuration.",
                    slug="oidc-misconfigured",
                )
            self._metadata = OidcMetadata(
                issuer=doc["issuer"],
                authorization_endpoint=doc["authorization_endpoint"],
                token_endpoint=doc["token_endpoint"],
                jwks_uri=doc["jwks_uri"],
                end_session_endpoint=doc.get("end_session_endpoint"),
            )
        return self._metadata

    async def _jwks_keys(self) -> Any:
        if self._jwks is None:
            meta = await self.metadata()
            response = await self._http.get(meta.jwks_uri)
            response.raise_for_status()
            self._jwks = JsonWebKey.import_key_set(response.json())
        return self._jwks

    @staticmethod
    def new_pkce_pair() -> tuple[str, str]:
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )
        return verifier, challenge

    async def build_authorize_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        meta = await self.metadata()
        params = httpx.QueryParams(
            response_type="code",
            client_id=self._settings.oidc_client_id,
            redirect_uri=redirect_uri,
            scope="openid email profile",
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )
        return f"{meta.authorization_endpoint}?{params}"

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> dict[str, Any]:
        meta = await self.metadata()
        response = await self._http.post(
            meta.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self._settings.oidc_client_id,
                "client_secret": self._settings.oidc_client_secret,
                "code_verifier": code_verifier,
            },
        )
        if response.status_code != 200:
            raise Problem(
                502,
                title="Sign-in failed",
                detail="The identity provider rejected the sign-in code exchange.",
                hint="Try signing in again; if it persists, check the IdP client settings.",
                slug="oidc-exchange-failed",
            )
        return dict(response.json())

    async def validate_id_token(self, id_token: str, *, nonce: str) -> dict[str, Any]:
        keys = await self._jwks_keys()
        claims = _jwt.decode(
            id_token,
            keys,
            claims_options={
                "iss": {"essential": True, "value": self._settings.oidc_issuer},
                "aud": {"essential": True, "value": self._settings.oidc_client_id},
                "exp": {"essential": True},
            },
        )
        claims.validate()
        if claims.get("nonce") != nonce:
            raise Problem(
                400,
                title="Sign-in failed",
                detail="The sign-in response could not be validated (nonce mismatch).",
                hint="Start the sign-in again from the app.",
                slug="oidc-invalid-token",
            )
        return dict(claims)
