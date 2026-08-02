"""The LiteLLM-backed adapter — the only place in OSAIP that touches a provider SDK.

Everything here exists to keep LiteLLM's surface from becoming OSAIP's surface (§10):

* **Wrapped, not exposed.** The rest of the platform sees `Provider`/`CompletionRequest`
  /`CompletionResult`. LiteLLM's kwargs, exception types and module globals stop here,
  so a LiteLLM upgrade is a change to one file rather than to every caller.
* **Nothing silently dropped.** Unknown `base_config` keys raise instead of being
  ignored. A config key that quietly does nothing is worse than an error: an operator
  sets `temperature_override`, sees no effect, and cannot tell whether it worked.
* **No module-global state.** LiteLLM invites `litellm.api_key = ...`; that is a
  process-wide mutation and this service handles many connections concurrently, so
  every credential and endpoint is passed per call.
* **Errors sanitised.** Raw provider text can carry the API key, an internal URL, or
  the prompt itself. Only `ProviderError` with a vetted message escapes.
* **SSRF re-checked per call.** `base_url` is validated on save AND here, because DNS
  can change between the two and the save-time check is not a guarantee at call time.
"""

from typing import Any

from osaip_mesh.cost import estimate_tokens
from osaip_mesh.providers.base import CompletionRequest, CompletionResult, ProviderError
from osaip_mesh.ssrf import UrlNotAllowed, validate_base_url

# LiteLLM routes on a `provider/model` prefix. Mapping it ourselves keeps the connection
# `provider` column authoritative — a model string cannot smuggle in a different vendor.
_PREFIX = {
    "openai": "openai",
    "anthropic": "anthropic",
    "ollama": "ollama",
}

# Every base_config key this adapter understands. Anything else is a hard error.
_ALLOWED_CONFIG = frozenset(
    {"base_url", "api_version", "organization", "timeout_s", "extra_headers", "drop_params"}
)

DEFAULT_TIMEOUT_S = 60.0

# Provider failures worth retrying (rate limits, transient upstream faults) vs those
# that will fail identically on retry (bad key, unknown model, malformed request).
_RETRYABLE = ("ratelimit", "timeout", "serviceunavailable", "apiconnection", "internalserver")


class LiteLLMProvider:
    """One instance per call, constructed with its connection's config and secret."""

    name = "litellm"

    def __init__(
        self,
        provider: str,
        config: dict[str, Any] | None = None,
        secret: str | None = None,
    ) -> None:
        config = dict(config or {})
        unknown = set(config) - _ALLOWED_CONFIG
        if unknown:
            # Loud, not lenient: a silently ignored setting is undebuggable.
            raise ProviderError(
                f"Unsupported connection settings: {', '.join(sorted(unknown))}. "
                f"Supported: {', '.join(sorted(_ALLOWED_CONFIG))}."
            )
        if provider not in _PREFIX:
            raise ProviderError(f"The {provider!r} provider is not supported by this adapter.")

        self._provider = provider
        self._secret = secret
        self._base_url = self._checked_base_url(config.get("base_url"))
        self._api_version = config.get("api_version")
        self._organization = config.get("organization")
        self._extra_headers = config.get("extra_headers") or {}
        self._timeout_s = float(config.get("timeout_s") or DEFAULT_TIMEOUT_S)
        # Off by default: silently dropping a parameter the caller asked for is exactly
        # the failure mode this adapter is built to avoid.
        self._drop_params = bool(config.get("drop_params", False))
        self._api_key = self._resolve_api_key(provider, secret, self._base_url)

    @staticmethod
    def _resolve_api_key(provider: str, secret: str | None, base_url: str | None) -> str | None:
        """Decide what to send as the credential, and refuse the one case that is always
        a misconfiguration.

        Without this, a keyless connection to api.openai.com surfaces as LiteLLM's
        "InternalServerError", which this adapter would classify as RETRYABLE — so a
        caller would retry forever against a connection that can never succeed.

        A self-hosted OpenAI-compatible endpoint (vLLM, LocalAI, Ollama) legitimately
        has no key, so a placeholder is sent to satisfy the client constructor. The
        hosted vendors always need a real one.
        """
        if secret:
            return secret
        if provider == "ollama" or base_url:
            # Self-hosted: the endpoint ignores it, but the SDK requires a non-empty
            # value to construct a client at all.
            return "osaip-no-credential"
        raise ProviderError(
            f"This {provider} connection has no API key. Attach a secret, or set a "
            "base_url if it points at a self-hosted endpoint that needs no credential."
        )

    @staticmethod
    def _checked_base_url(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ProviderError("base_url must be a string.")
        try:
            return validate_base_url(value)
        except UrlNotAllowed as exc:
            # The URL is operator-supplied, so echoing it back is safe and necessary —
            # it is the one detail that makes the refusal actionable.
            raise ProviderError(f"base_url rejected: {exc}") from exc

    def _model_id(self, model: str) -> str:
        prefix = _PREFIX[self._provider]
        return model if model.startswith(f"{prefix}/") else f"{prefix}/{model}"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        import litellm

        kwargs: dict[str, Any] = {
            "model": self._model_id(request.model),
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "timeout": self._timeout_s,
            "drop_params": self._drop_params,
            # Per-call, never `litellm.api_key = ...`: this process serves many
            # connections at once and a module global would leak one's key into another.
            "api_key": self._api_key,
        }
        if self._base_url:
            kwargs["api_base"] = self._base_url
        if self._api_version:
            kwargs["api_version"] = self._api_version
        if self._organization:
            kwargs["organization"] = self._organization
        if self._extra_headers:
            kwargs["extra_headers"] = dict(self._extra_headers)

        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            raise _sanitize(exc) from exc

        return _to_result(response, request=request)


def _sanitize(exc: Exception) -> ProviderError:
    """Map any LiteLLM/provider exception to a message that is safe to show.

    The exception's TEXT is never forwarded: provider errors routinely echo the request
    body (the prompt, hence any PII the guardrails just redacted for the audit) and
    sometimes the Authorization header. Only the class name shapes the message.
    """
    kind = type(exc).__name__
    lowered = kind.lower()
    retryable = any(marker in lowered for marker in _RETRYABLE)
    if "authentication" in lowered or "permission" in lowered:
        message = "The provider rejected the credentials for this connection."
    elif "notfound" in lowered:
        message = "The provider does not recognise this model."
    elif "badrequest" in lowered or "unprocessable" in lowered:
        message = "The provider rejected the request parameters."
    elif "contextwindow" in lowered:
        message = "The prompt is longer than this model's context window."
    elif retryable:
        message = "The provider is unavailable or rate limiting; retry shortly."
    else:
        message = "The model provider could not complete the request."
    return ProviderError(f"{message} ({kind})", retryable=retryable)


def _to_result(response: Any, *, request: CompletionRequest) -> CompletionResult:
    """Read LiteLLM's response defensively — it is a moving target across versions."""
    try:
        choice = response.choices[0]
        content = choice.message.content or ""
    except (AttributeError, IndexError, TypeError) as exc:
        raise ProviderError("The provider returned an unreadable response.") from exc

    usage = getattr(response, "usage", None)
    tokens_in = _reported(getattr(usage, "prompt_tokens", None))
    tokens_out = _reported(getattr(usage, "completion_tokens", None))
    # A provider that omits usage gets an ESTIMATE, flagged as such — the ledger must
    # never present a guess as a measurement (ADR-0008 §2).
    #
    # ZERO counts as "not reported", not as a measurement: LiteLLM synthesises a usage
    # object with zeros when the upstream omits one, so trusting it would silently
    # record every such call as costing nothing — under-reporting real spend, which is
    # exactly the failure the ledger exists to prevent. A non-empty prompt cannot
    # legitimately be zero tokens.
    estimated = tokens_in is None or tokens_out is None
    if tokens_in is None:
        tokens_in = sum(estimate_tokens(m.content) for m in request.messages)
    if tokens_out is None:
        tokens_out = estimate_tokens(content) if content else 0

    return CompletionResult(
        content=content,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        # The model the provider actually served, which can differ from what was asked
        # for (aliases, silent upgrades) — the ledger records both.
        model_version=str(getattr(response, "model", None) or request.model),
        tokens_estimated=estimated,
    )


def _reported(value: Any) -> int | None:
    """A usable token count, or None when the provider did not really report one."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value) if value > 0 else None
