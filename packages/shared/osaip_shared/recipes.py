"""Recipe config schemas (spec §3.2 "Visual recipe JSON") + the canonical config
hash. These pydantic models are the contract between the API (validation, storage)
and the engine (compilation). Kept in shared so both import one definition.
"""

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# ── Prepare steps ────────────────────────────────────────────────────────────────


class RenameStep(BaseModel):
    op: Literal["rename"] = "rename"
    mapping: dict[str, str] = Field(min_length=1)  # {old: new}


class CastStep(BaseModel):
    op: Literal["cast"] = "cast"
    casts: dict[str, str] = Field(min_length=1)  # {column: duck_type}


class FilterStep(BaseModel):
    op: Literal["filter"] = "filter"
    expression: str = Field(min_length=1, max_length=4000)


class FormulaStep(BaseModel):
    op: Literal["formula"] = "formula"
    column: str = Field(min_length=1, max_length=200)
    expression: str = Field(min_length=1, max_length=4000)


class FillNullsStep(BaseModel):
    op: Literal["fill_nulls"] = "fill_nulls"
    values: dict[str, Any] = Field(min_length=1)  # {column: literal}


class DedupeStep(BaseModel):
    op: Literal["dedupe"] = "dedupe"
    subset: list[str] = Field(default_factory=list)  # empty = all columns


class SelectStep(BaseModel):
    op: Literal["select"] = "select"
    columns: list[str] = Field(min_length=1)
    drop: bool = False  # False = keep only `columns`; True = drop `columns`


PrepareStep = Annotated[
    RenameStep | CastStep | FilterStep | FormulaStep | FillNullsStep | DedupeStep | SelectStep,
    Field(discriminator="op"),
]


class PrepareConfig(BaseModel):
    kind: Literal["prepare"] = "prepare"
    steps: list[PrepareStep] = Field(min_length=1)


# ── Join / group / stack / split / sample ────────────────────────────────────────


class JoinKey(BaseModel):
    left: str
    right: str


class JoinConfig(BaseModel):
    kind: Literal["join"] = "join"
    how: Literal["inner", "left", "right", "outer"] = "inner"
    on: list[JoinKey] = Field(min_length=1)
    right_suffix: str = Field(default="_right", max_length=32)


class Aggregation(BaseModel):
    column: str
    func: Literal["sum", "min", "max", "mean", "count", "count_distinct"]
    as_: str = Field(alias="as")

    model_config = {"populate_by_name": True}


class GroupConfig(BaseModel):
    kind: Literal["group"] = "group"
    by: list[str] = Field(min_length=1)
    aggregations: list[Aggregation] = Field(min_length=1)


class StackConfig(BaseModel):
    kind: Literal["stack"] = "stack"
    # union-by-name across all inputs; missing columns fill NULL


class SplitConfig(BaseModel):
    kind: Literal["split"] = "split"
    expression: str = Field(min_length=1, max_length=4000)  # rows matching → output 0


class SampleConfig(BaseModel):
    kind: Literal["sample"] = "sample"
    method: Literal["head", "random"] = "head"
    n: int | None = Field(default=1000, ge=1, le=10_000_000)
    fraction: float | None = Field(default=None, gt=0, le=1)
    seed: int = 42


# ── Code recipes ─────────────────────────────────────────────────────────────────


class SqlConfig(BaseModel):
    kind: Literal["sql"] = "sql"
    query: str = Field(min_length=1, max_length=100_000)


class PythonConfig(BaseModel):
    kind: Literal["python"] = "python"
    code: str = Field(min_length=1, max_length=200_000)


RecipeConfig = Annotated[
    PrepareConfig
    | JoinConfig
    | GroupConfig
    | StackConfig
    | SplitConfig
    | SampleConfig
    | SqlConfig
    | PythonConfig,
    Field(discriminator="kind"),
]

# Number of inputs each recipe kind requires (min, max|None for unbounded).
INPUT_ARITY: dict[str, tuple[int, int | None]] = {
    "prepare": (1, 1),
    "join": (2, 2),
    "group": (1, 1),
    "stack": (2, None),
    "split": (1, 1),
    "sample": (1, 1),
    "sql": (1, None),
    "python": (1, None),
}

# Number of outputs each recipe kind produces.
OUTPUT_ARITY: dict[str, int] = {
    "prepare": 1,
    "join": 1,
    "group": 1,
    "stack": 1,
    "split": 2,  # match, rest
    "sample": 1,
    "sql": 1,
    "python": 1,
}


def config_hash(config: dict[str, Any]) -> str:
    """Canonical hash of a recipe config (ADR-0007 §2). Computed from the validated
    dict with sorted keys / compact separators / ensure_ascii=False — NEVER from a
    jsonb read-back, which would reorder keys and normalize numbers."""
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
