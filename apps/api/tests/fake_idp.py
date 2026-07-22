"""In-process fake OIDC provider served over httpx.MockTransport.

The fake token endpoint cannot know the nonce of the authorize request (the browser
never reaches it in tests), so tests pass the nonce AS the authorization code — the
handler signs the id_token with nonce=code.
"""

import datetime
import json
from typing import Any
from urllib.parse import parse_qs

import httpx
from authlib.jose import JsonWebKey, JsonWebToken

from osaip_api.config import Settings

_jwt = JsonWebToken(["RS256"])


class FakeIdp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        self.subject = "fake-sub-1"
        self.email = "admin@osaip.dev"
        self.name = "Ada Admin"
        self.sid = "fake-sid-1"
        self.token_requests: list[dict[str, list[str]]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport())

    def _sign_id_token(self, nonce: str) -> str:
        now = datetime.datetime.now(datetime.UTC)
        payload = {
            "iss": self.settings.oidc_issuer,
            "aud": self.settings.oidc_client_id,
            "sub": self.subject,
            "email": self.email,
            "name": self.name,
            "sid": self.sid,
            "nonce": nonce,
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + 300,
        }
        token: bytes = _jwt.encode({"alg": "RS256"}, payload, self.key)
        return token.decode("ascii")

    def _handle(self, request: httpx.Request) -> httpx.Response:
        internal = self.settings.oidc_internal_base
        issuer = self.settings.oidc_issuer
        url = str(request.url)
        if url == f"{internal}/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": f"{issuer}/protocol/openid-connect/auth",
                    "token_endpoint": f"{internal}/protocol/openid-connect/token",
                    "jwks_uri": f"{internal}/protocol/openid-connect/certs",
                    "end_session_endpoint": f"{issuer}/protocol/openid-connect/logout",
                },
            )
        if url == f"{internal}/protocol/openid-connect/certs":
            key_dict: dict[str, Any] = json.loads(self.key.as_json(is_private=False))
            key_dict["kid"] = "fake-key"
            return httpx.Response(200, json={"keys": [key_dict]})
        if url == f"{internal}/protocol/openid-connect/token":
            form = parse_qs(request.content.decode("ascii"))
            self.token_requests.append(form)
            if not form.get("code") or not form.get("code_verifier"):
                return httpx.Response(400, json={"error": "invalid_request"})
            nonce = form["code"][0]
            return httpx.Response(
                200,
                json={
                    "access_token": "fake-access-token",
                    "token_type": "Bearer",
                    "id_token": self._sign_id_token(nonce),
                },
            )
        return httpx.Response(404, json={"error": "unknown fake IdP url", "url": url})
