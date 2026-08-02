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


# An ESTIMATE, never a measurement. Used to size a quota reservation (which settles to
# the truth) and as the fallback when a provider omits usage — where the ledger flags
# `tokens_estimated` so nothing downstream mistakes it for exact.
#
# tiktoken when it is available, because the estimate is what a quota HOLDS: a count
# that is off by 2x either blocks legitimate calls or lets a budget overshoot, and
# characters-per-token drifts badly on Dutch, on code and on punctuation-heavy text.
_CHARS_PER_TOKEN = 4
_ENCODING_NAME = "o200k_base"


@lru_cache(maxsize=1)
def _encoder() -> Any | None:
    """Loaded once, and never fatal: tiktoken arrives transitively with LiteLLM, so an
    install without it must still be able to size a reservation."""
    try:
        import tiktoken

        return tiktoken.get_encoding(_ENCODING_NAME)
    except Exception:
        # Includes the offline case: tiktoken fetches its BPE file on first use, and an
        # air-gapped install has no network. Falling back is correct — this is an
        # estimate, and the ledger never bills from it.
        return None


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    encoder = _encoder()
    if encoder is not None:
        return max(1, len(encoder.encode(text, disallowed_special=())))
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)
