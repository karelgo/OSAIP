"""LLM recipes: ONE compiler, four modes (spec §7 Phase 3, ADR-0010).

Unlike every other recipe, an LLM recipe does not compile to an Ibis `Table` — it
compiles to a PLAN the worker executes per row, because each row is a network call. So
this module produces a description of what to send, and knows nothing about how it is
sent: no mesh import, no HTTP, no async. That keeps the interesting parts (prompt
assembly, untrusted wrapping, CP-1 derivation) testable without a service.

The AC says a classify recipe must run "via two different connections with identical
code path". Four near-copies of a compiler is how that stops being true, so the modes
differ only in their system prompt and how their answer is turned into a column.

**Where the prompt comes from, precisely** (§5d):
  · the SYSTEM role is assembled here, server-side, from a fixed per-mode template. It
    is never taken from recipe config — a client that can write the system role can
    rewrite the task.
  · the USER role is the recipe's own template over columns (the spec's "free template
    on columns"), with every interpolated cell wrapped by `untrusted_block()`.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from osaip_engine.errors import InvalidInput
from osaip_guardrails.untrusted import untrusted_block

LLM_KINDS = ("llm_prompt", "llm_classify", "llm_extract", "llm_summarize")

# CP-1's ladder, strictest last. Duplicated from osaip_api.propagation deliberately:
# packages/engine must not import the API (it is the lower layer).
_CLASS_ORDER = ("none", "persoonsgegevens", "bijzonder", "bsn")

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_ .-]*)\}")

# Assembled server-side, per mode. Deliberately terse: a long system prompt is more
# surface for an injected instruction to contradict.
_SYSTEM: dict[str, str] = {
    "llm_prompt": "Answer using only the data provided. Reply with the answer alone.",
    "llm_classify": (
        "Classify the data provided into exactly one of the given labels. "
        "Reply with the label alone, and nothing else."
    ),
    "llm_extract": (
        "Extract the requested fields from the data provided. "
        "Reply with JSON only, matching the given schema. Use null for anything absent."
    ),
    "llm_summarize": "Summarise the data provided. Reply with the summary alone.",
}


@dataclass(frozen=True)
class LlmPlan:
    """What to send for one row, and what to do with the answer."""

    kind: str
    system_prompt: str
    template: str
    output_column: str
    # Columns the template interpolates — the set the CP-1 floor is computed over, and
    # the only cells that reach the model.
    interpolated_columns: tuple[str, ...]
    output_schema: dict[str, Any] | None = None
    labels: tuple[str, ...] = ()
    max_tokens: int = 512
    extra: dict[str, Any] = field(default_factory=dict)

    def render_user_message(self, row: dict[str, Any]) -> str:
        """Interpolate one row. Every value goes through `untrusted_block()` — a dataset
        cell is attacker-controlled input, and this is the only sanctioned way to put one
        in a prompt (§5d)."""

        def substitute(match: re.Match[str]) -> str:
            column = match.group(1)
            value = row.get(column)
            text = "" if value is None else str(value)
            return untrusted_block(text, label=_safe_label(column))

        return _PLACEHOLDER.sub(substitute, self.template)

    def messages(self, row: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.render_user_message(row)},
        ]


def _safe_label(column: str) -> str:
    """The label lands inside the delimiter, so it must not be able to close it."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", column)[:40] or "cell"


def compile_llm_recipe(kind: str, config: dict[str, Any], available_columns: list[str]) -> LlmPlan:
    """Validate config and build the plan. One function, four modes."""
    if kind not in LLM_KINDS:
        raise InvalidInput(f"{kind} is not an LLM recipe.")

    template = config.get("template")
    if not isinstance(template, str) or not template.strip():
        raise InvalidInput("An LLM recipe needs a non-empty `template`.")

    referenced = tuple(dict.fromkeys(_PLACEHOLDER.findall(template)))
    if not referenced:
        # A template with no columns sends the same prompt for every row — an expensive
        # way to get one answer N times, and almost always a typo in the placeholders.
        raise InvalidInput(
            "The template references no columns. Use {column_name} to include row data."
        )
    unknown = [column for column in referenced if column not in available_columns]
    if unknown:
        raise InvalidInput(f"Unknown column(s) in template: {', '.join(sorted(unknown))}.")

    output_column = config.get("output_column") or _default_output(kind)
    if not isinstance(output_column, str) or not output_column.strip():
        raise InvalidInput("`output_column` must be a non-empty name.")
    if output_column in available_columns:
        # Overwriting an input column would make the recipe non-reproducible: a rebuild
        # would read its own previous output.
        raise InvalidInput(
            f"`{output_column}` already exists on the input. Pick a new column name."
        )

    system = _SYSTEM[kind]
    labels: tuple[str, ...] = ()
    schema: dict[str, Any] | None = None
    max_tokens = int(config.get("max_tokens") or _default_max_tokens(kind))

    if kind == "llm_classify":
        raw_labels = config.get("labels")
        if not isinstance(raw_labels, list) or len(raw_labels) < 2:
            raise InvalidInput("`llm_classify` needs at least two `labels`.")
        labels = tuple(str(label) for label in raw_labels)
        if len(set(labels)) != len(labels):
            raise InvalidInput("`labels` must be unique.")
        system = f"{system}\nLabels: {', '.join(labels)}."
        # The label set is also enforced on the way back, so a model that invents a
        # label produces a row error rather than a value nobody expected.
        schema = {"type": "string", "enum": list(labels)}

    if kind == "llm_extract":
        schema = config.get("schema")
        if not isinstance(schema, dict) or not schema:
            raise InvalidInput("`llm_extract` needs a JSON `schema`.")
        system = f"{system}\nSchema: {schema}."

    if kind == "llm_summarize":
        sentences = config.get("max_sentences")
        if sentences is not None:
            system = f"{system} Use at most {int(sentences)} sentences."

    return LlmPlan(
        kind=kind,
        system_prompt=system,
        template=template,
        output_column=output_column,
        interpolated_columns=referenced,
        output_schema=schema,
        labels=labels,
        max_tokens=max_tokens,
    )


def _default_output(kind: str) -> str:
    return {
        "llm_prompt": "llm_output",
        "llm_classify": "label",
        "llm_extract": "extracted",
        "llm_summarize": "summary",
    }[kind]


def _default_max_tokens(kind: str) -> int:
    # A classify answer is one word; letting it default to 512 would reserve — and
    # potentially spend — two orders of magnitude more than the task needs.
    return {"llm_classify": 16, "llm_extract": 512, "llm_summarize": 256, "llm_prompt": 512}[kind]


def classification_floor(
    columns: tuple[str, ...],
    column_classifications: dict[str, str] | None,
    dataset_classification: str,
) -> str:
    """The CP-1 label the mesh must be told about, over the columns actually sent.

    Derived rather than defaulted, because both defaults are wrong: the mesh fails
    closed to `bijzonder` (blocking every build on a non-local connection), and a
    hardcoded `none` would silently defeat the CP-11 gate at the exact path where
    citizen data first reaches an external model (ADR-0010).

    Falls back to the DATASET label when a column has no label of its own — an unlabelled
    column in a `bsn` dataset is treated as `bsn`, never as `none`.
    """
    labels = [dataset_classification]
    for column in columns:
        labels.append((column_classifications or {}).get(column) or dataset_classification)
    return max(labels, key=lambda label: _rank(label))


def _rank(label: str | None) -> int:
    try:
        return _CLASS_ORDER.index(label or "none")
    except ValueError:
        # An unknown label is treated as the strictest, not ignored.
        return len(_CLASS_ORDER)
