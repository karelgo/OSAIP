# ADR-0009: the Dutch NER model is operator-installed, not redistributed

- **Status**: accepted
- **Date**: 2026-08-01
- **Deciders**: karel goense (approved 2026-08-01)
- **Supersedes**: the `nl_core_news_sm` line in `docs/plans/phase-3a.md` §"New dependencies",
  which recorded the model as MIT. That was **wrong**.

## Context

Phase 3a's guardrails add a model-backed PII pass (Presidio) on top of the deterministic
detectors, using the Dutch spaCy model `nl_core_news_sm` — a choice the user made
explicitly during Phase 3 planning.

The approved plan listed the model as MIT. It is not. Package metadata for
`nl_core_news_sm==3.8.0` (Explosion) reports:

```
License: CC BY-SA 4.0
```

The §3.1 license gate (`scripts/check_licenses.py`) failed on it, which is what the gate
is for. Presidio itself (`presidio-analyzer`, `presidio-anonymizer`) and the spaCy
library are MIT and pass unchanged; the question is only about the **model artifact**.

CC BY-SA 4.0 is a share-alike license. The usual reading is that ShareAlike binds
*adaptations of the licensed work* — a fine-tuned or modified model — and not software
that merely loads it, so redistributing the model unmodified inside an image is
permitted with attribution. That reading is probably correct, and it is what most
projects do.

It is also not the only reading, and OSAIP's target deployments are Dutch public-sector
organisations whose procurement and legal review scrutinise every license in the supply
chain. A defensible-by-inspection answer is worth more here than a probably-fine one.

## Decision

**OSAIP does not redistribute the model.**

1. `presidio-analyzer` / `presidio-anonymizer` / `spacy` (all MIT) stay as an **optional
   extra** of `osaip-guardrails`, and `apps/mesh` depends on that extra. Code ships;
   the model does not.
2. The OSAIP image does **not** install `nl_core_news_sm`. Operators who want
   name/place/date detection install the pinned wheel themselves, per
   `docs/deployment.md`. That is a one-line step, and an air-gapped install has to
   stage such artifacts deliberately anyway.
3. The **deterministic layer is unaffected and always on**: BSN (11-proef), IBAN
   (mod-97), email and phone need no model, no network and no extra. This is the layer
   that carries the compliance weight (CP-1/CP-11, AVG), and it keeps working in an
   install that never touches Presidio.
4. `presidio_nl.get_engine()` raises a clear `PresidioUnavailable` naming the missing
   model rather than silently degrading to regex-only. A policy that asked for Presidio
   and did not get it must say so.
5. CI installs the pinned wheel so the Presidio code path is genuinely exercised; `make
   spacy-model` does the same locally. Neither is a runtime download.
6. `CC BY-SA` is **not** added to the license allowlist. The gate stays strict, and a
   future attempt to bake the model in will fail it again — which is the point.

## Consequences

- Out of the box, OSAIP redacts BSN/IBAN/email/phone but not names or places. An
  operator who needs the latter takes one documented step. The Usage/connection UI
  should show whether the model-backed pass is actually available, so nobody assumes
  coverage they do not have.
- No copyleft-adjacent artifact in anything OSAIP distributes.
- If a permissively-licensed Dutch NER model of comparable quality appears, we can bake
  it in and drop the extra step; nothing above depends on the model being absent.

## Alternatives considered

- **Ship it with an allowlist exception + NOTICE attribution.** Common practice and
  probably fine, but puts CC BY-SA in the supply chain of a public-sector deliverable
  for a capability that is a supplement, not the core control. Rejected.
- **Drop the NER layer entirely.** License-clean and simplest, but throws away a
  capability the user explicitly asked for, over a problem solvable with one install
  step. Rejected.
- **Find a permissive Dutch NER model.** No drop-in of comparable quality identified.
  Left open — see Consequences.
