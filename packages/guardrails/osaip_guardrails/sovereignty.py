"""CP-11 data sovereignty: which classifications may leave which boundary.

This lives at the mesh's choke point rather than in each caller. A rule enforced in one
caller is a rule that the next caller forgets; a rule enforced where every model call
must pass cannot be routed around (spec §5b).

**Residency is operator-asserted metadata, not a technical guarantee** (ADR-0008 §7).
`data_residency='local'` records that an operator declared this endpoint to run inside
their own boundary. The platform enforces the declaration consistently and audits it; it
cannot verify where a remote endpoint actually runs. Documented as such so a
deployment's DPIA does not mistake it for proof.
"""

from osaip_guardrails.types import Action, GuardrailEvent

# CP-1's classification ladder, strictest last.
CLASSIFICATIONS = ("none", "persoonsgegevens", "bijzonder", "bsn")

RESIDENCIES = ("local", "eu", "external")

# Where each classification is allowed to go. Special-category data and the BSN (Wabb:
# the BSN may only be used where the law names a purpose) never leave the local boundary.
_ALLOWED: dict[str, frozenset[str]] = {
    "none": frozenset({"local", "eu", "external"}),
    "persoonsgegevens": frozenset({"local", "eu"}),
    "bijzonder": frozenset({"local"}),
    "bsn": frozenset({"local"}),
}


def normalise_classification(value: str | None) -> str:
    """An unknown or missing declaration fails CLOSED — treated as `bijzonder`.

    The alternative (defaulting to `none`) means a caller that forgets to declare gets
    the most permissive routing, which is precisely backwards.
    """
    if value in _ALLOWED:
        return value
    return "bijzonder"


def is_allowed(classification: str, residency: str) -> bool:
    return residency in _ALLOWED[normalise_classification(classification)]


def check_residency(
    *, classification: str | None, residency: str, connection_name: str | None = None
) -> tuple[bool, GuardrailEvent]:
    """Decide whether this payload may go to this connection, with the event either way.

    An allowed call still emits an event: CP-11 accountability is about being able to
    show what was routed where, not only about the refusals.
    """
    declared = normalise_classification(classification)
    allowed = is_allowed(declared, residency)
    details = {
        "classification": declared,
        "declared_as": classification,
        "residency": residency,
        "connection": connection_name,
        # Recorded on every event so an audit reader is never left thinking the platform
        # verified the geography.
        "residency_is_operator_asserted": True,
    }
    return allowed, GuardrailEvent(
        stage="pre",
        rule="cp11.residency",
        action=Action.ALLOW if allowed else Action.BLOCK,
        details=details,
    )


def refusal_reason(classification: str | None, residency: str) -> str:
    """User-facing text. A block must say what to change, not just that it failed."""
    declared = normalise_classification(classification)
    allowed = ", ".join(sorted(_ALLOWED[declared]))
    suffix = (
        " (no classification was declared, so it was treated as `bijzonder`)"
        if normalise_classification(classification) != classification
        else ""
    )
    return (
        f"Data classified `{declared}` may only be sent to a connection whose data "
        f"residency is {allowed}; this connection is `{residency}`{suffix}."
    )
