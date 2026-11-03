"""ProxyAPI image models: ids and prices, RUB per 1M tokens (input, output), with 5% VAT.

Source: https://proxyapi.ru/models/browse (tab "Изображения"), 2026-11-03. The catalog text
available to us is cut off after 47 of 51 models, and the price of sourceful/riverflow-v2-pro is
missing: for models not listed here set PROXYAPI_IMAGE_PRICE_IN_RUB / _OUT_RUB.
Keep in sync with docs/MODELS_AND_COSTS.md §3.
"""

PRICES_RUB_PER_1M: dict[str, tuple[float, float]] = {
    "black-forest-labs/flux-3-image-klein": (263.16, 263.16),
    "black-forest-labs/flux-3-image": (1157.89, 1157.89),
    "tencent/hy-image-v3.5-preview": (221.05, 221.05),
    "krea/krea-2-medium-turbo": (484.21, 484.21),
    "bytedance-seed/seedream-5-0-flash": (578.95, 578.95),
    "qwen/qwen-image-2.1-turbo": (600.0, 600.0),
    "sourceful/riverflow-v2.5-fast": (621.05, 621.05),
    "sourceful/riverflow-v2-fast": (652.63, 652.63),
    "meta/muse-image": (736.84, 736.84),
    "qwen/qwen-image-3": (968.42, 968.42),
    "krea/krea-2-medium": (968.42, 968.42),
    "krea/k3-edit": (968.42, 968.42),
    "bytedance-seed/seedream-5-0-lite": (1157.89, 1157.89),
    "recraft/recraft-v4-styles": (1157.89, 1157.89),
    "recraft/recraft-v4.1": (1157.89, 1157.89),
    "recraft/recraft-v4.1-utility": (1157.89, 1157.89),
    "qwen/qwen-image-3-pro": (1368.42, 1368.42),
    "recraft/recraft-v3": (1368.42, 1368.42),
    "recraft/recraft-v4": (1368.42, 1368.42),
    "bytedance-seed/seedream-5-0-pro": (1473.68, 1473.68),
    "qwen/qwen-image-2.1-pro": (1578.95, 1578.95),
    "recraft/recraft-v4-styles-vector": (1684.21, 1684.21),
    "x-ai/grok-imagine-image-2.0": (1894.74, 1894.74),
    "krea/krea-2-large": (2000.0, 2000.0),
    "microsoft/mai-image-2.6-flash": (2631.58, 2631.58),
    "recraft/recraft-v4-vector": (2631.58, 2631.58),
    "recraft/recraft-v4.1-vector": (2631.58, 2631.58),
    "recraft/recraft-v4-styles-pro": (3263.16, 3263.16),
    "recraft/recraft-v4-styles-pro-vector": (3894.74, 3894.74),
    "sourceful/riverflow-v2.6-pro": (4210.53, 4210.53),
    "sourceful/riverflow-v2.5-pro": (4210.53, 4210.53),
    "microsoft/mai-image-2.6": (5157.89, 5157.89),
    "microsoft/mai-image-2.5": (6315.79, 6315.79),
    "recraft/recraft-v4.1-pro": (6842.11, 6842.11),
    "recraft/recraft-v4.1-utility-pro": (6842.11, 6842.11),
    "recraft/recraft-v4-pro": (8105.26, 8105.26),
    "recraft/recraft-v4-pro-vector": (9684.21, 9684.21),
    "recraft/recraft-v4.1-pro-vector": (9684.21, 9684.21),
    "microsoft/mai-image-2.5-pro": (14736.84, 14736.84),
    "google/gemini-3.1-flash-lite-image": (76.0, 9100.0),
    "google/gemini-3.1-flash-image": (76.0, 18200.0),
    "google/gemini-nano-banana-2.1": (455.0, 9100.0),
    "google/gemini-3-pro-image": (632.0, 36843.0),
    "openai/gpt-image-2": (1520.0, 9100.0),
    "openai/gpt-image-2.5-flare": (1520.0, 9100.0),
    "openai/gpt-image-2.5-sunburst": (1520.0, 9100.0),
}


def prices_for(
    model: str, override_in: float = 0.0, override_out: float = 0.0
) -> tuple[float, float]:
    """Settings override the table; (0, 0) for a model that is in neither."""
    if override_in or override_out:
        return override_in, override_out
    return PRICES_RUB_PER_1M.get(model, (0.0, 0.0))
