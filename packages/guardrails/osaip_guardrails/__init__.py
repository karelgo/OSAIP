"""OSAIP guardrails: PII detection/redaction, the §5d prompt-injection posture, and the
CP-11 sovereignty gate. Guardrails are not optional — see `policy`."""

from osaip_guardrails.detectors import detect_all, is_valid_bsn, is_valid_iban
from osaip_guardrails.policy import BASELINE, PolicyConfig, merge_policy, run_pre
from osaip_guardrails.redact import redact
from osaip_guardrails.sovereignty import check_residency, normalise_classification, refusal_reason
from osaip_guardrails.types import (
    Action,
    Detection,
    GuardrailBlocked,
    GuardrailEvent,
    StageResult,
)
from osaip_guardrails.untrusted import has_delimiter_syntax, untrusted_block

__all__ = [
    "BASELINE",
    "Action",
    "Detection",
    "GuardrailBlocked",
    "GuardrailEvent",
    "PolicyConfig",
    "StageResult",
    "check_residency",
    "detect_all",
    "has_delimiter_syntax",
    "is_valid_bsn",
    "is_valid_iban",
    "merge_policy",
    "normalise_classification",
    "redact",
    "refusal_reason",
    "run_pre",
    "untrusted_block",
]
