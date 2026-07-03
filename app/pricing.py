"""OpenAI price table + credit conversion math.

All prices are USD per 1,000,000 tokens (the unit OpenAI publishes).
Prices are approximate defaults; the admin can override the effective
markup / unit price from the panel. Unknown models fall back to a safe
default so the accounting never divides by zero.
"""
from __future__ import annotations

import math

# USD per 1M tokens: (input, output). Image models handled separately.
# gpt-5.4/5.5 prices are estimates (post-knowledge-cutoff models) — admin
# can compensate via mode markup if OpenAI bills differently.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o3": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "gpt-5.1": (1.25, 10.00),
    "gpt-5.2": (1.25, 10.00),
    "gpt-5.4-nano": (0.06, 0.50),
    "gpt-5.4-mini": (0.30, 2.40),
    "gpt-5.4": (1.25, 10.00),
    "gpt-5.4-pro": (15.00, 120.00),
    "gpt-5.5": (1.50, 12.00),
    "gpt-5.5-pro": (15.00, 120.00),
    "gpt-5-search-api": (1.25, 10.00),
    "gpt-image-1": (5.00, 40.00),  # token-based image model (approx)
    "gpt-image-2": (5.00, 40.00),
}

# Unknown model => assume flagship-tier pricing so we never undercharge.
DEFAULT_PRICE = (2.50, 10.00)

# Approximate flat USD cost per generated image by size/quality (gpt-image-1).
IMAGE_FLAT_USD = {
    ("1024x1024", "low"): 0.011,
    ("1024x1024", "medium"): 0.042,
    ("1024x1024", "high"): 0.167,
    ("1024x1536", "medium"): 0.063,
    ("1536x1024", "medium"): 0.063,
    ("1024x1536", "high"): 0.25,
    ("1536x1024", "high"): 0.25,
}


def model_price(model: str) -> tuple[float, float]:
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    # longest-prefix match so dated variants (gpt-5.5-2026-04-23) resolve
    best: str | None = None
    for key in MODEL_PRICES:
        if model.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return MODEL_PRICES[best] if best else DEFAULT_PRICE


def api_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int = 0,
) -> float:
    """Real OpenAI cost in USD. Reasoning tokens are billed as output."""
    p_in, p_out = model_price(model)
    billed_output = output_tokens + reasoning_tokens
    return (input_tokens * p_in + billed_output * p_out) / 1_000_000.0


def usd_to_ai_tokens(
    api_usd: float,
    *,
    markup: float,
    unit_price_usd: float,
    base_credit_cost: int = 0,
    min_charge: int = 1,
    max_charge: int = 100_000,
) -> int:
    """Convert real API USD cost into internal AI-Token charge.

    charged = base + ceil(api_usd * markup / unit_price_usd)
    """
    if unit_price_usd <= 0:
        unit_price_usd = 0.0005
    internal_usd = api_usd * markup
    tokens = base_credit_cost + math.ceil(internal_usd / unit_price_usd)
    tokens = max(tokens, min_charge)
    tokens = min(tokens, max_charge)
    return int(tokens)
