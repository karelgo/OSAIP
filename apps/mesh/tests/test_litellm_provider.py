"""The LiteLLM adapter, driven against a real OpenAI-compatible HTTP server.

Phase 3a's first acceptance clause is that echo and a real provider share ONE code
path. Mocking `litellm.acompletion` would prove nothing — the mock would be the code
path — so these run LiteLLM against a local server speaking the real wire format.

The stub listens on loopback, which the SSRF guard blocks by default. Every test here
therefore also demonstrates the operator allowlist (`OSAIP_MESH_URL_ALLOWLIST`) that
exists for on-prem endpoints, and one test asserts the block is real without it.
"""

import uuid
from typing import Any
from unittest import mock

import httpx
import pytest
from openai_stub import openai_stub
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCall
from osaip_mesh.providers.base import CompletionRequest, Message, ProviderError
from osaip_mesh.providers.litellm_provider import LiteLLMProvider


def _request(content: str = "hallo wereld", **kwargs: Any) -> CompletionRequest:
    return CompletionRequest(
        model=kwargs.pop("model", "gpt-4o-mini"),
        messages=[Message(role="user", content=content)],
        max_tokens=kwargs.pop("max_tokens", 64),
        temperature=kwargs.pop("temperature", 0.0),
    )


@pytest.fixture
def allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SSRF guard blocks loopback by default; on-prem operators allowlist a host.
    Doing the same here keeps the guard ON for every other test."""
    monkeypatch.setenv("OSAIP_MESH_URL_ALLOWLIST", "127.0.0.1,localhost")


# ── the adapter against a real server ───────────────────────────────────────────


async def test_a_real_completion_round_trip(allow_loopback: None) -> None:
    with openai_stub() as stub:
        provider = LiteLLMProvider("openai", {"base_url": stub["base_url"]}, "sk-test")
        result = await provider.complete(_request("hallo wereld"))

    assert result.content == "stub: hallo wereld"
    assert result.tokens_in == 2
    assert result.tokens_out == 3
    assert result.tokens_estimated is False
    # What the provider SERVED, not what was asked for.
    assert result.model_version == "stub-model-2026-01"


async def test_the_request_reaches_the_provider_intact(allow_loopback: None) -> None:
    """Parameters must not be silently dropped on the way through LiteLLM."""
    with openai_stub() as stub:
        provider = LiteLLMProvider("openai", {"base_url": stub["base_url"]}, "sk-test")
        await provider.complete(_request("meet dit", max_tokens=99, temperature=0.25))
        sent = stub["requests"][0]

    assert sent["path"].endswith("/chat/completions")
    assert sent["body"]["max_tokens"] == 99
    assert sent["body"]["temperature"] == 0.25
    assert sent["body"]["messages"] == [{"role": "user", "content": "meet dit"}]
    assert sent["authorization"] == "Bearer sk-test"


async def test_the_provider_prefix_is_ours_not_the_callers(allow_loopback: None) -> None:
    """The connection's `provider` column is authoritative: a model string must not be
    able to smuggle in a different vendor."""
    with openai_stub() as stub:
        provider = LiteLLMProvider("openai", {"base_url": stub["base_url"]}, "sk-test")
        await provider.complete(_request(model="anthropic/claude-sonnet-4"))
        sent = stub["requests"][0]
    # LiteLLM strips the routing prefix before the wire call; the point is that it went
    # to OUR openai-compatible endpoint, not to Anthropic.
    assert "claude-sonnet-4" in sent["body"]["model"]


async def test_missing_usage_falls_back_to_a_flagged_estimate(allow_loopback: None) -> None:
    """A guess must never be presented as a measurement (ADR-0008 §2)."""
    with openai_stub("no_usage") as stub:
        provider = LiteLLMProvider("openai", {"base_url": stub["base_url"]}, "sk-test")
        result = await provider.complete(_request("een wat langere zin om te tellen"))

    assert result.tokens_estimated is True
    assert result.tokens_in > 0
    assert result.tokens_out > 0


async def test_a_malformed_response_is_a_clean_provider_error(allow_loopback: None) -> None:
    with openai_stub("malformed") as stub:
        provider = LiteLLMProvider("openai", {"base_url": stub["base_url"]}, "sk-test")
        with pytest.raises(ProviderError):
            await provider.complete(_request())


# ── error sanitisation ──────────────────────────────────────────────────────────


async def test_an_auth_failure_leaks_neither_key_nor_prompt(allow_loopback: None) -> None:
    """Real providers echo the API key and the request body in 401s. The prompt may
    contain exactly the PII the guardrails just redacted for storage."""
    with openai_stub("unauthorized") as stub:
        provider = LiteLLMProvider("openai", {"base_url": stub["base_url"]}, "sk-SECRETKEY123")
        with pytest.raises(ProviderError) as excinfo:
            await provider.complete(_request("BSN 111222333"))

    message = excinfo.value.public_message
    assert "sk-SECRETKEY123" not in message
    assert "111222333" not in message
    assert stub["base_url"] not in message
    assert excinfo.value.retryable is False  # a bad key is not worth retrying


async def test_a_rate_limit_is_marked_retryable(allow_loopback: None) -> None:
    with openai_stub("rate_limited") as stub:
        provider = LiteLLMProvider("openai", {"base_url": stub["base_url"]}, "sk-test")
        with pytest.raises(ProviderError) as excinfo:
            await provider.complete(_request())
    assert excinfo.value.retryable is True


# ── configuration discipline ────────────────────────────────────────────────────


def test_unknown_config_keys_are_rejected_not_ignored() -> None:
    """A setting that silently does nothing is undebuggable: the operator sees no
    effect and cannot tell whether it applied."""
    with pytest.raises(ProviderError) as excinfo:
        LiteLLMProvider("openai", {"temperature_override": 0.9}, "sk-test")
    assert "temperature_override" in excinfo.value.public_message


def test_an_unsupported_provider_is_rejected() -> None:
    with pytest.raises(ProviderError):
        LiteLLMProvider("some-vendor", {}, "sk-test")


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1:11434/v1",  # loopback, without the allowlist
        "file:///etc/passwd",
        "http://user:pass@example.com/v1",
    ],
)
def test_ssrf_guard_runs_at_construction(url: str) -> None:
    """Validated on save AND here: DNS can change between the two, so the save-time
    check is not a guarantee at call time."""
    with pytest.raises(ProviderError):
        LiteLLMProvider("openai", {"base_url": url}, "sk-test")


def test_an_allowlisted_on_prem_host_is_permitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The escape hatch that makes Ollama-on-the-compose-network reachable."""
    monkeypatch.setenv("OSAIP_MESH_URL_ALLOWLIST", "127.0.0.1")
    provider = LiteLLMProvider("ollama", {"base_url": "http://127.0.0.1:11434/v1"}, None)
    assert provider is not None


# ── through the whole mesh pipeline ─────────────────────────────────────────────


async def test_two_connections_one_code_path(
    mesh_client: httpx.AsyncClient,
    mesh_session: AsyncSession,
    make_connection: Any,
    allow_loopback: None,
) -> None:
    """Phase 3a acceptance clause 1: echo and a real provider produce ledger rows of
    the same shape, because they went through the same pipeline."""
    echo = await make_connection()
    with openai_stub() as stub:
        real = await make_connection(
            provider="openai",
            allowed_models=["gpt-4o-mini"],
            data_residency="external",
            base_config={"base_url": stub["base_url"]},
        )
        bodies = []
        for connection, model in ((echo, "echo-1"), (real, "gpt-4o-mini")):
            response = await mesh_client.post(
                "/v1/complete",
                json={
                    "connection_id": str(connection.id),
                    "model": model,
                    "messages": [{"role": "user", "content": "hallo"}],
                    "max_classification": "none",
                },
            )
            assert response.status_code == 200, response.text
            bodies.append(response.json())

    for body in bodies:
        assert body["call_id"] and body["trace_id"]
        assert body["currency"] == "EUR"
        assert body["tokens_in"] > 0
        call = await mesh_session.get(LlmCall, uuid.UUID(body["call_id"]))
        assert call is not None and call.status == "ok"

    # The real one is PRICED, so the cost path is exercised with non-zero arithmetic —
    # every earlier test ran against echo at zero.
    assert bodies[0]["cost_micros"] == 0  # echo
    assert bodies[1]["cost_micros"] > 0  # gpt-4o-mini
    assert bodies[1]["pricing_unknown"] is False
    assert bodies[1]["model_version"] == "stub-model-2026-01"


async def test_redaction_happens_before_the_real_provider(
    mesh_client: httpx.AsyncClient, make_connection: Any, allow_loopback: None
) -> None:
    """The strongest form of the guarantee: inspect what the provider ACTUALLY
    received over the wire."""
    with openai_stub() as stub:
        connection = await make_connection(
            provider="openai",
            allowed_models=["gpt-4o-mini"],
            data_residency="local",
            base_config={"base_url": stub["base_url"]},
        )
        await mesh_client.post(
            "/v1/complete",
            json={
                "connection_id": str(connection.id),
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "BSN 111222333 en 1234.56.782"}],
                "max_classification": "bsn",
            },
        )
        received = stub["requests"][0]["body"]["messages"][0]["content"]

    assert "111222333" not in received
    assert "1234.56.782" not in received
    assert received.count("<BSN>") == 2


# ── credential policy (found while wiring the pipeline, 2026-08-02) ──────────────


def test_a_keyless_hosted_connection_fails_clearly_not_as_a_retryable_502() -> None:
    """Without this the SDK's own "InternalServerError" surfaced, which `_sanitize`
    classifies as RETRYABLE — so a caller would retry forever against a connection that
    can never succeed."""
    with pytest.raises(ProviderError) as excinfo:
        LiteLLMProvider("openai", {}, None)
    assert "no API key" in excinfo.value.public_message
    assert excinfo.value.retryable is False


def test_a_keyless_self_hosted_endpoint_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """vLLM/LocalAI/Ollama behind a base_url legitimately need no credential."""
    monkeypatch.setenv("OSAIP_MESH_URL_ALLOWLIST", "127.0.0.1")
    assert LiteLLMProvider("openai", {"base_url": "http://127.0.0.1:8000/v1"}, None) is not None
    assert LiteLLMProvider("ollama", {}, None) is not None


async def test_a_zero_usage_report_is_treated_as_unreported(allow_loopback: None) -> None:
    """LiteLLM synthesises a zero `usage` when the upstream omits one. Trusting it would
    record the call as costing nothing and silently under-report real spend."""
    with openai_stub("no_usage") as stub:
        provider = LiteLLMProvider("openai", {"base_url": stub["base_url"]}, "sk-test")
        result = await provider.complete(_request("tel deze woorden alsjeblieft"))
    assert result.tokens_estimated is True
    assert result.tokens_in > 0
    assert result.tokens_out > 0


def test_token_estimates_are_sane_and_degrade_safely() -> None:
    """The estimate sizes a quota HOLD, so being off by 2x either blocks legitimate
    calls or lets a budget overshoot. It must also never be fatal: tiktoken arrives
    transitively with LiteLLM and fetches its BPE file on first use, so an air-gapped
    install has to fall back rather than fail."""
    from osaip_mesh import cost

    assert cost.estimate_tokens("") == 0
    assert cost.estimate_tokens("hallo wereld") > 0
    # Roughly proportional: 10x the text is not 100x the tokens.
    short = cost.estimate_tokens("de cliënt belde vandaag")
    long = cost.estimate_tokens("de cliënt belde vandaag " * 10)
    assert 8 * short <= long <= 12 * short

    cost._encoder.cache_clear()
    try:
        with mock.patch.dict("sys.modules", {"tiktoken": None}):
            assert cost.estimate_tokens("hallo wereld") > 0  # chars/4 fallback
    finally:
        cost._encoder.cache_clear()
