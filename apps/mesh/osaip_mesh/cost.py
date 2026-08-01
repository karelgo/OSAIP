"""Cost computation in integer micros (ADR-0008 §2).

Money is never a float: `cost_micros` is an integer count of millionths of a currency
unit, with the currency recorded alongside it. Rounding is half-up on the computed
TOTAL — never truncation per token, which would systematically under-bill. An unknown
model costs 0 and is flagged `pricing_unknown`; the platform never guesses a price.
"""

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

_PRICES_PATH = Path(__file__).parent / "model_prices.json"
_MTOK = Decimal(1_000_000)


@dataclass(frozen=True)
class CostResult:
    cost_micros: int
    currency: str
    pricing_unknown: bool


@lru_cache(maxsize=1)
def _price_table() -> tuple[dict[str, dict[str, int]], str, str]:
    data: dict[str, Any] = json.loads(_PRICES_PATH.read_text(encoding="utf-8"))
    return data["prices"], data["_currency"], data["_verified_on"]


def price_key(provider: str, model: str) -> str:
    return f"{provider}/{model}"


def verified_on() -> str:
    """The date the pinned price table was last checked (surfaced in the UI)."""
    return _price_table()[2]


def compute_cost(provider: str, model: str, tokens_in: int, tokens_out: int) -> CostResult:
    prices, currency, _ = _price_table()
    entry = prices.get(price_key(provider, model))
    if entry is None:
        return CostResult(cost_micros=0, currency=currency, pricing_unknown=True)
    total = (
        Decimal(tokens_in) * Decimal(entry["in_per_mtok_micros"])
        + Decimal(tokens_out) * Decimal(entry["out_per_mtok_micros"])
    ) / _MTOK
    # Half-up on the total (not per token): truncating each term would under-bill.
    rounded = int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return CostResult(cost_micros=rounded, currency=currency, pricing_unknown=False)


def known_models() -> list[str]:
    return sorted(_price_table()[0])


# ~4 characters per token is the usual English/Dutch rule of thumb. It is only ever used
# to size a quota RESERVATION (which settles to the truth), never to bill or to report —
# billing always uses the provider's reported usage. tiktoken lands with the LiteLLM
# adapter, where a provider may omit usage and the ledger flags `tokens_estimated`.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)
