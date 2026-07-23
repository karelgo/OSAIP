"""CP-1 / CP-2 label propagation across recipe inputs → outputs (ADR-0007 §7).

CP-1 classification is a conservative ladder; the output floor is the MAX of inputs.
CP-2 purpose_codes are INTERSECTED (doelbinding — union would let joined data be used
for a purpose neither source permitted); legal_basis is a provenance union.
"""

from collections.abc import Sequence

from osaip_api.models import Dataset

_CLASS_ORDER = ["none", "persoonsgegevens", "bijzonder", "bsn"]
_BBN_ORDER = [None, "bbn1", "bbn2", "bbn3"]
_CONF_ORDER = [None, "intern", "vertrouwelijk", "geheim"]


def _max(values: Sequence[str | None], order: Sequence[str | None]) -> str | None:
    return max(values, key=lambda v: order.index(v)) if values else order[0]


def classification_floor(inputs: list[Dataset]) -> tuple[str, str | None, str | None]:
    """MAX classification / bbn_level / confidentiality across inputs (the floor)."""
    classification = _max([d.classification for d in inputs], _CLASS_ORDER) or "none"
    bbn = _max([d.bbn_level for d in inputs], _BBN_ORDER)
    conf = _max([d.confidentiality for d in inputs], _CONF_ORDER)
    return classification, bbn, conf


def apply_classification_floor(output: Dataset, inputs: list[Dataset]) -> None:
    """Ratchet: raise the output to the floor, never silently lower a manual raise
    (a manual value already above the floor is preserved)."""
    classification, bbn, conf = classification_floor(inputs)
    if _CLASS_ORDER.index(output.classification) < _CLASS_ORDER.index(classification):
        output.classification = classification
    if _BBN_ORDER.index(output.bbn_level) < _BBN_ORDER.index(bbn):
        output.bbn_level = bbn
    if _CONF_ORDER.index(output.confidentiality) < _CONF_ORDER.index(conf):
        output.confidentiality = conf


def purpose_intersection(inputs: list[Dataset]) -> list[str]:
    """Intersection of input purpose sets, order-stable by the first input."""
    if not inputs:
        return []
    common: set[str] = set(inputs[0].purpose_codes)
    for dataset in inputs[1:]:
        common &= set(dataset.purpose_codes)
    return [code for code in inputs[0].purpose_codes if code in common]


def legal_basis_union(inputs: list[Dataset]) -> str:
    seen: list[str] = []
    for dataset in inputs:
        if dataset.legal_basis and dataset.legal_basis not in seen:
            seen.append(dataset.legal_basis)
    return " · ".join(seen) if seen else "Derived (see inputs)"
