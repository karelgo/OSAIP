"""The Dutch model-backed layer.

Skipped only when the model is genuinely absent — CI installs the pinned wheel, so
these run there. A skip locally means "run `make spacy-model`", not "this is optional".
"""

import pytest

from osaip_guardrails.policy import merge_policy, run_pre_async
from osaip_guardrails.presidio_nl import analyze, is_available, reset_engine

pytestmark = pytest.mark.skipif(
    not is_available(), reason="nl_core_news_sm not installed — run `make spacy-model`"
)

SENTENCE = "Jan de Vries woont in Amsterdam en belde op 3 maart 2026."


def test_dutch_names_and_places_are_found() -> None:
    kinds = {d.kind for d in analyze(SENTENCE)}
    assert "person" in kinds
    assert "location" in kinds


def test_detections_carry_a_score_and_their_source() -> None:
    detection = next(d for d in analyze(SENTENCE) if d.kind == "person")
    assert detection.detector == "presidio"
    assert 0.0 < detection.score <= 1.0
    assert SENTENCE[detection.start : detection.end] == "Jan de Vries"


def test_empty_text_needs_no_model_pass() -> None:
    assert analyze("   ") == []


def test_the_engine_is_built_once() -> None:
    """Loading spaCy costs ~100 MB; paying that per call would be unusable."""
    reset_engine()
    from osaip_guardrails import presidio_nl

    first = presidio_nl.get_engine()
    assert presidio_nl.get_engine() is first


async def test_the_async_pass_redacts_a_dutch_name() -> None:
    policy = merge_policy({"pre": {"presidio": True}})
    result = await run_pre_async("Jan de Vries belde over BSN 111222333.", policy)
    assert "Jan de Vries" not in result.text
    assert "111222333" not in result.text
    assert "<PERSON>" in result.text and "<BSN>" in result.text


async def test_presidio_is_off_unless_the_policy_asks() -> None:
    """The model pass costs latency; the deterministic layer is what is always on."""
    result = await run_pre_async("Jan de Vries belde.", merge_policy(None))
    assert "Jan de Vries" in result.text


async def test_the_deterministic_layer_keeps_first_claim() -> None:
    """A checksum beats a score: the BSN must be labelled <BSN>, not a generic number."""
    policy = merge_policy({"pre": {"presidio": True}})
    result = await run_pre_async("BSN 111222333 van Jan de Vries.", policy)
    assert "<BSN>" in result.text
    rules = [e.rule for e in result.events]
    assert rules == ["pii.regex", "pii.presidio"]  # regex first, in that order


async def test_both_passes_are_evented_separately() -> None:
    """An operator needs to see which layer caught what — the deterministic one is
    evidence, the probabilistic one is a judgement call."""
    policy = merge_policy({"pre": {"presidio": True}})
    result = await run_pre_async("Jan de Vries, BSN 111222333.", policy)
    by_rule = {e.rule: e for e in result.events}
    assert by_rule["pii.regex"].details["counts"] == {"bsn": 1}
    assert by_rule["pii.presidio"].details["model"] == "nl_core_news_sm"
    assert "111222333" not in str(by_rule["pii.presidio"].details)
