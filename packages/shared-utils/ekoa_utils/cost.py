"""Rough per-call cost estimation based on token counts.

These numbers are ESTIMATES, not billed figures: they are derived from
publicly listed list prices for the providers EKOA can call and do not read
real invoices. Pricing changes; treat everything here as an approximation
for internal observability only.

Units: USD per 1,000,000 tokens.
"""

from __future__ import annotations

# ── Per-1M-token USD list prices (approximate, label as estimate) ───────────

_PROVIDER_PRICES: dict[str, dict[str, tuple[float, float]]] = {
    # provider -> {model-substring: (input_per_1m, output_per_1m)}
    "deepseek": {
        "reasoner": (0.55, 2.19),
        "chat": (0.27, 1.10),
    },
    "gemini": {
        "flash": (0.10, 0.40),
        "pro": (1.25, 5.00),
    },
}


def _match_prices(provider: str, model: str | None) -> tuple[float, float] | None:
    table = _PROVIDER_PRICES.get(provider)
    if not table:
        return None
    m = (model or "").lower()
    if not m:
        return table.get("chat") or table.get("flash") or next(iter(table.values()))
    # Longest matching key wins (e.g. "deepseek-reasoner" beats "deepseek-chat"
    # prefix variants because "reasoner" is the more specific substring).
    matches = [(k, v) for k, v in table.items() if k in m]
    if not matches:
        return table.get("chat") or table.get("flash") or next(iter(table.values()))
    return max(matches, key=lambda kv: len(kv[0]))[1]


def estimate_call_cost(
    provider: str | None,
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    """Estimate the USD cost of one LLM call from token counts.

    Returns ``None`` when we cannot price it (unknown provider or missing
    token counts). The result is rounded to 6 decimals (sub-milli-cent) and is
    explicitly an estimate — not a billed amount.
    """
    if not provider or prompt_tokens is None or completion_tokens is None:
        return None
    prices = _match_prices(provider.lower(), model)
    if prices is None:
        return None
    input_per_1m, output_per_1m = prices
    cost = (prompt_tokens / 1_000_000) * input_per_1m + (
        completion_tokens / 1_000_000
    ) * output_per_1m
    return round(cost, 6)