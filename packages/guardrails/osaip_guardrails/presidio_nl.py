"""Model-backed PII detection, Dutch (ADR-0008 §5).

This layer runs AFTER the deterministic detectors, never instead of them. Presidio finds
what a checksum cannot — names, addresses, locations, dates of birth — but it is
probabilistic, and a probabilistic detector must never be the only thing standing
between a BSN and a third party.

Three properties this module exists to guarantee:

1. **Lazy.** Loading spaCy costs hundreds of milliseconds and ~100 MB. An install that
   never enables Presidio must not pay for it, and the mesh must not pay it per call —
   so the engine is built once, on first use, and cached.
2. **Never downloads, and never shipped.** `nl_core_news_sm` is CC BY-SA 4.0, so OSAIP
   does not redistribute it — an operator installs the pinned wheel (ADR-0009). If it is
   missing we raise a clear error; we do NOT fetch it at runtime, which would break
   air-gapped installs and silently change behaviour mid-deployment, and we do NOT
   quietly fall back to regex-only, because a policy that asked for Presidio should be
   told it did not get it.
3. **Blocking work stays off the event loop.** spaCy is CPU-bound and synchronous;
   `analyze_async` offloads it to a thread so one PII scan cannot stall the mesh.
"""

import asyncio
import threading
from typing import Any

from osaip_guardrails.types import Detection

SPACY_MODEL = "nl_core_news_sm"
LANGUAGE = "nl"

# Presidio's entity names mapped onto ours. Anything not listed is ignored rather than
# passed through under an unfamiliar label an operator would have to guess at.
_ENTITY_KINDS = {
    "PERSON": "person",
    "LOCATION": "location",
    "DATE_TIME": "date",
    "NRP": "nationality",
    "MEDICAL_LICENSE": "license",
    "IP_ADDRESS": "ip",
    "CREDIT_CARD": "credit_card",
}

# The deterministic layer already owns these and does it better (checksums), so letting
# Presidio also report them would double-count and could downgrade a BSN to a generic
# number.
_HANDLED_BY_REGEX = {"EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE"}

DEFAULT_THRESHOLD = 0.6

_engine: Any = None
_engine_error: str | None = None
_lock = threading.Lock()


class PresidioUnavailable(RuntimeError):
    """Presidio or the Dutch model is not installed. Raised rather than silently
    downgrading to regex-only: a policy that asked for Presidio should be told it did
    not get it."""


def _build_engine() -> Any:
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError as exc:  # pragma: no cover - exercised by the extras-less install
        raise PresidioUnavailable(
            "presidio-analyzer is not installed; install osaip-guardrails[presidio]."
        ) from exc

    import spacy

    if not spacy.util.is_package(SPACY_MODEL):
        raise PresidioUnavailable(
            f"The spaCy model {SPACY_MODEL!r} is not installed. OSAIP does not ship it "
            "(CC BY-SA 4.0, ADR-0009) and never downloads a model at runtime — install "
            "the pinned wheel, see docs/deployment-checklist.md."
        )

    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": LANGUAGE, "model_name": SPACY_MODEL}],
        }
    )
    return AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=[LANGUAGE])


def get_engine() -> Any:
    """Build once, reuse forever. The lock matters: two concurrent first-calls would
    otherwise each load spaCy, doubling the memory cost for no benefit."""
    global _engine, _engine_error
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        if _engine_error is not None:
            # Don't retry a load that already failed on every call; the cause (a missing
            # model) does not fix itself, and retrying just adds latency to each request.
            raise PresidioUnavailable(_engine_error)
        try:
            _engine = _build_engine()
        except PresidioUnavailable as exc:
            _engine_error = str(exc)
            raise
        return _engine


def reset_engine() -> None:
    """Test hook — drops the cached engine and any remembered failure."""
    global _engine, _engine_error
    with _lock:
        _engine, _engine_error = None, None


def is_available() -> bool:
    """Whether a Presidio scan can run, without raising. Used to show an operator that a
    policy asking for Presidio will actually get it."""
    try:
        get_engine()
    except PresidioUnavailable:
        return False
    return True


def analyze(text: str, *, threshold: float = DEFAULT_THRESHOLD) -> list[Detection]:
    """Blocking. Call `analyze_async` from async code."""
    if not text.strip():
        return []
    results = get_engine().analyze(text=text, language=LANGUAGE)
    detections: list[Detection] = []
    for item in results:
        if item.entity_type in _HANDLED_BY_REGEX:
            continue
        kind = _ENTITY_KINDS.get(item.entity_type)
        if kind is None or item.score < threshold:
            continue
        detections.append(
            Detection(
                kind=kind,
                start=item.start,
                end=item.end,
                detector="presidio",
                score=float(item.score),
            )
        )
    return detections


async def analyze_async(text: str, *, threshold: float = DEFAULT_THRESHOLD) -> list[Detection]:
    """spaCy is CPU-bound and synchronous; keep it off the event loop."""
    return await asyncio.to_thread(analyze, text, threshold=threshold)
