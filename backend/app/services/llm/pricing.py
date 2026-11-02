"""ProxyAPI prices, RUB per 1M tokens (input, output).

Source: https://proxyapi.ru/pricing, 2026-11-02. Keep in sync with docs/MODELS_AND_COSTS.md.
"""

PRICES_RUB_PER_1M: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (30.0, 150.0),
    "deepseek-v4.1-flash": (26.07, 100.25),
}

# Unknown model: assume the primary model's price so costs are not under-reported.
_DEFAULT_PRICE = PRICES_RUB_PER_1M["claude-haiku-5-5"]


def cost_rub(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES_RUB_PER_1M.get(model, _DEFAULT_PRICE)
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000
