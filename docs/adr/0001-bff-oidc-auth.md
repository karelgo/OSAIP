# ADR-0001: BFF session-cookie OIDC (server-side sessions, CSRF, logout)

Status: Accepted · 2026-07-22 · Phase 0

## Context
Spec §3.2 locks OIDC (Keycloak dev, generic OIDC in code). The web app needs an auth
pattern. SPA-held tokens (implicit/PKCE in browser) expose tokens to XSS and complicate
guardrails; a Backend-for-Frontend keeps tokens server-side.

## Decision
- **BFF pattern.** `apps/api` runs the authorization-code + PKCE flow server-side via
  Authlib. The browser only ever holds an opaque, itsdangerous-signed random session id
  in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` in prod). Signed ≠ encrypted, so the
  cookie carries **no claims or tokens** — only the random id.
- **Server-side sessions.** A `sessions` row (id, user_id, oidc_sub, oidc_sid indexed,
  id_token, expires_at) backs each cookie. Access/refresh tokens are **discarded after
  the callback** — nothing in Phase 0 calls downstream with them; the `id_token` is kept
  server-side solely for logout. The `oidc_sid` index enables backchannel logout later.
  Starlette SessionMiddleware is used only for the transient state/nonce/PKCE verifier
  during the login dance.
- **Dual-hostname Keycloak.** In compose the browser reaches Keycloak at
  `localhost:8080`, the api container at `keycloak:8080`. `KC_HOSTNAME=localhost:8080`
  pins the issuer to the external URL; Authlib is configured with explicit endpoints
  (authorization endpoint browser-facing; token + JWKS container-internal) and asserts
  `iss` equals the external issuer.
- **CSRF.** Cookie auth is ambient, so middleware rejects state-changing requests whose
  `Origin`/`Sec-Fetch-Site` indicates cross-site. `?next=` on `/auth/login` must be a
  same-origin relative path (starts with `/`, no `//`, no scheme) to prevent open
  redirects.
- **Logout** is RP-initiated: delete the session row, then redirect to Keycloak's
  `end_session_endpoint` with `id_token_hint` + `post_logout_redirect_uri`, so role
  switching in dev actually re-authenticates.
- **SSE exemption.** `packages/api-client` is generated; hand-written fetch is
  forbidden (§3.2). The one recorded exemption is the EventSource-based SSE client,
  which the generator cannot produce.

## Consequences
Tokens never reach the browser; sessions are revocable server-side; CSRF and
open-redirect defenses are testable in pytest. Cost: a DB read per request for session
lookup (acceptable; cacheable later) and slightly more moving parts than a pure SPA flow.
