"""Policy composition.

**Guardrails are not optional** (BIO2 8.12, ADR-0008 §5). Every connection gets the
baseline PII redaction whether or not it names a policy, and a policy can only ADD to
the baseline — there is no configuration that turns redaction off. Making it removable
would mean one mis-set dropdown is the difference between a redacted audit trail and
a plaintext BSN in a third party's logs.

`audit_mode='full'` is the sanctioned, admin-only, itself-audited way to retain raw
text; it stores the original alongside the redacted copy, it does not stop redaction
from happening before the provider call.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from osaip_guardrails.redact import apply_redactions, redact
from osaip_guardrails.schema import validate_json_text
from osaip_guardrails.types import Action, GuardrailEvent, StageResult


@dataclass(frozen=True)
class PolicyConfig:
    """A connection's guardrail settings, already merged with the baseline."""

    # Always on. Present as a field only so the value shows up in an audit of the
    # effective policy; nothing can set it False.
    redact_pii: bool = True
    # Optional additions a policy may switch on.
    use_presidio: bool = False
    max_input_chars: int | None = None
    judge_model: str | None = None
    output_schema: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


BASELINE = PolicyConfig()


def merge_policy(
    stages: dict[str, Any] | None, request_output_schema: dict[str, Any] | None = None
) -> PolicyConfig:
    """Build the effective policy from a `guardrail_policies.stages` document.

    Unknown keys are ignored rather than rejected so an older node can still run a
    policy written by a newer one; anything that would DISABLE the baseline is ignored
    too, which is the point.

    `request_output_schema` is the per-call shape an `llm_extract` recipe requires. It
    can only ADD a constraint: if the connection's policy already pins a schema, that
    one wins, because a caller must not be able to loosen a shape an operator set
    (ADR-0010 §4 — the same add-never-remove rule as the PII baseline).
    """
    stages = stages or {}
    pre = stages.get("pre", {}) if isinstance(stages.get("pre"), dict) else {}
    post = stages.get("post", {}) if isinstance(stages.get("post"), dict) else {}

    max_chars = pre.get("max_input_chars")
    schema = post.get("schema")
    if not isinstance(schema, dict) and isinstance(request_output_schema, dict):
        schema = request_output_schema
    return PolicyConfig(
        redact_pii=True,  # deliberately not read from the document
        use_presidio=bool(pre.get("presidio", False)),
        max_input_chars=int(max_chars) if isinstance(max_chars, int) and max_chars > 0 else None,
        judge_model=post.get("judge_model") if isinstance(post.get("judge_model"), str) else None,
        output_schema=schema if isinstance(schema, dict) else None,
        extra={k: v for k, v in stages.items() if k not in {"pre", "post"}},
    )


def run_pre(text: str, policy: PolicyConfig) -> StageResult:
    """The `pre` stage: length guard, then redaction.

    Length is checked BEFORE redaction so a caller cannot smuggle an oversized payload
    past the limit by relying on placeholders to shrink it.
    """
    events: list[GuardrailEvent] = []
    if policy.max_input_chars is not None and len(text) > policy.max_input_chars:
        return StageResult(
            text=text,
            blocked=True,
            reason=(
                f"The prompt is {len(text)} characters; this connection's policy allows "
                f"{policy.max_input_chars}."
            ),
            events=[
                GuardrailEvent(
                    stage="pre",
                    rule="input.max_chars",
                    action=Action.BLOCK,
                    details={"length": len(text), "limit": policy.max_input_chars},
                )
            ],
        )

    result = redact(text, stage="pre")
    events.extend(result.events)
    return StageResult(text=result.text, events=events)


def run_post(text: str, policy: PolicyConfig) -> StageResult:
    """The `post` stage: validate the shape, then redact for storage.

    Redaction here protects the AUDIT copy — a model can echo a BSN back that the caller
    never sent. The caller still receives the model's actual answer; what changes is
    what the platform writes down.

    A schema failure BLOCKS: the caller asked for a specific shape, and handing back
    something else silently is how malformed data enters a dataset.
    """
    events: list[GuardrailEvent] = []
    if policy.output_schema is not None:
        problems = validate_json_text(text, policy.output_schema)
        if problems:
            return StageResult(
                text=text,
                blocked=True,
                reason=f"The model's response did not match the required shape: {problems[0]}",
                events=[
                    GuardrailEvent(
                        stage="post",
                        rule="output.schema",
                        action=Action.BLOCK,
                        # Problem descriptions, not the response body.
                        details={"problems": problems[:5], "problem_count": len(problems)},
                    )
                ],
            )
        events.append(
            GuardrailEvent(
                stage="post", rule="output.schema", action=Action.ALLOW, details={"valid": True}
            )
        )

    redacted = redact(text, stage="post")
    events.extend(redacted.events)
    return StageResult(text=redacted.text, events=events)


async def run_pre_async(text: str, policy: PolicyConfig) -> StageResult:
    """`run_pre` plus the optional model-backed pass.

    Presidio runs over the ALREADY-REDACTED text: the deterministic layer has first
    claim (its checksums beat any score), and running second keeps offsets valid without
    a merge step. Import is local so the package still works with the extra uninstalled.
    """
    result = run_pre(text, policy)
    if result.blocked or not policy.use_presidio:
        return result

    from osaip_guardrails.presidio_nl import analyze_async

    detections = await analyze_async(result.text)
    if not detections:
        return result

    counts = Counter(d.kind for d in detections)
    return StageResult(
        text=apply_redactions(result.text, detections),
        events=[
            *result.events,
            GuardrailEvent(
                stage="pre",
                rule="pii.presidio",
                action=Action.REDACT,
                details={
                    "counts": dict(sorted(counts.items())),
                    "total": len(detections),
                    "model": "nl_core_news_sm",
                },
            ),
        ],
    )
