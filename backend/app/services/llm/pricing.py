"""ProxyAPI text-model ids and prices, RUB per 1M tokens (input, output), with 5% VAT.

Source: https://proxyapi.ru/models/browse, 2026-11-03. Ids carry the vendor prefix. Keep in sync
with docs/MODELS_AND_COSTS.md.
"""

PRICES_RUB_PER_1M: dict[str, tuple[float, float]] = {
    "anthropic/claude-haiku-5-5": (30.0, 150.0),
    "anthropic/claude-sonnet-5-5": (500.0, 2500.0),
    "deepseek/deepseek-v4.1-flash": (26.07, 100.25),
    "openai/gpt-6-luna": (30.0, 150.0),
    "qwen/qwen3.8-flash": (20.0, 65.0),
}

# Unknown model: assume the primary model's price so costs are not under-reported.
_DEFAULT_PRICE = PRICES_RUB_PER_1M["anthropic/claude-haiku-5-5"]


def cost_rub(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES_RUB_PER_1M.get(model, _DEFAULT_PRICE)
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000
