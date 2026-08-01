"""Cost math (ADR-0008 §2): integer micros, half-up on the total, explicit currency,
unknown model → 0 + flag (never a guess)."""

from osaip_mesh.cost import compute_cost, known_models, verified_on


def test_known_model_costs_are_exact_integers() -> None:
    # gpt-4o: 2.30 EUR / Mtok in, 9.20 EUR / Mtok out.
    # 1000 in  → 1000 * 2_300_000 / 1_000_000 = 2300 micros
    # 500 out  →  500 * 9_200_000 / 1_000_000 = 4600 micros
    result = compute_cost("openai", "gpt-4o", 1000, 500)
    assert result.cost_micros == 6900
    assert result.currency == "EUR"
    assert result.pricing_unknown is False
    assert isinstance(result.cost_micros, int)


def test_rounding_is_half_up_on_the_total_not_per_token() -> None:
    # 1 token at 138_000 micros/Mtok = 0.138 micros → rounds to 0 alone,
    # but the TOTAL is what rounds: 4 in + 0 out = 0.552 → 1 (half-up), not 0.
    assert compute_cost("openai", "gpt-4o-mini", 1, 0).cost_micros == 0
    assert compute_cost("openai", "gpt-4o-mini", 4, 0).cost_micros == 1
    # .5 exactly rounds up (half-up, not banker's)
    assert compute_cost("openai", "gpt-4o-mini", 5, 0).cost_micros == 1


def test_unknown_model_is_flagged_never_guessed() -> None:
    result = compute_cost("openai", "gpt-does-not-exist", 10_000, 10_000)
    assert result.cost_micros == 0
    assert result.pricing_unknown is True


def test_local_providers_are_free_but_known() -> None:
    result = compute_cost("echo", "echo-1", 1000, 1000)
    assert result.cost_micros == 0
    assert result.pricing_unknown is False  # free ≠ unknown


def test_price_table_is_pinned_and_dated() -> None:
    assert verified_on()  # the table records when it was last checked
    assert "openai/gpt-4o" in known_models()
