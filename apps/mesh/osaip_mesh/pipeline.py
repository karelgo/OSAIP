"""THE mesh pipeline (spec §5b, ADR-0008 §1).

    authz → CP-11 residency gate → guardrails `pre` (redact) → quota reserve
          → cache lookup (on the REDACTED payload) → provider
          → guardrails `post` → settle (ledger + audit + span)

The deviation from §5b's literal order (redaction ahead of cache/provider) is
deliberate and recorded in ADR-0008 §1: the literal order defeats its own acceptance
criterion, because a cache hit would skip redaction and store raw PII, and the cache
key would be computed over raw text.

Slice 1 wires the skeleton and the provider call; the ledger/cache (slice 2), quotas
(slice 3) and guardrails/CP-11 (slice 4) fill in the marked seams.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from osaip_mesh.cost import compute_cost
from osaip_mesh.providers.base import (
    CompletionRequest,
    CompletionResult,
    Message,
    Provider,
    ProviderError,
)


@dataclass
class CallContext:
    """What the caller declares about this call. `max_classification` is mandatory for
    the CP-11 gate — a missing declaration fails closed (treated `bijzonder`)."""

    project_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    purpose: str = "general"
    max_classification: str = "bijzonder"
    trace_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    job_step_id: uuid.UUID | None = None
    row_key: str | None = None
    depth: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MeshOutcome:
    content: str
    tokens_in: int
    tokens_out: int
    cost_micros: int
    currency: str
    pricing_unknown: bool
    tokens_estimated: bool
    cache_hit: bool
    latency_ms: int
    model_version: str | None
    call_id: uuid.UUID | None = None
    guardrail_events: list[dict[str, Any]] = field(default_factory=list)


async def run_pipeline(
    *,
    provider: Provider,
    provider_name: str,
    request: CompletionRequest,
    context: CallContext,
) -> MeshOutcome:
    """Execute one model call through the mesh. Blocking work belongs in the stages;
    this function owns the ORDER, which is the part that must never drift."""
    started = time.perf_counter()

    # ── CP-11 residency gate + guardrails `pre` land in slice 4 ──────────────────
    # ── quota reserve lands in slice 3 ───────────────────────────────────────────
    # ── cache lookup (redacted payload) lands in slice 2 ─────────────────────────

    try:
        result: CompletionResult = await provider.complete(request)
    except ProviderError:
        raise
    except Exception as exc:  # adapters must not leak raw driver/HTTP text (keys!)
        raise ProviderError("The model provider could not be reached.") from exc

    # ── guardrails `post` lands in slice 4 ───────────────────────────────────────

    cost = compute_cost(provider_name, request.model, result.tokens_in, result.tokens_out)
    latency_ms = int((time.perf_counter() - started) * 1000)

    # ── settle: ledger + audit + span land in slices 2-3 ─────────────────────────

    return MeshOutcome(
        content=result.content,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_micros=cost.cost_micros,
        currency=cost.currency,
        pricing_unknown=cost.pricing_unknown,
        tokens_estimated=result.tokens_estimated,
        cache_hit=False,
        latency_ms=latency_ms,
        model_version=result.model_version,
    )


def messages_from_payload(payload: list[dict[str, str]]) -> list[Message]:
    return [Message(role=item["role"], content=item["content"]) for item in payload]
