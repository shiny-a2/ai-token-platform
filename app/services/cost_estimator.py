"""Cost estimation + actual-charge computation.

estimate() runs BEFORE a request to show the user a min/max credit range.
compute_charge() runs AFTER, converting real token usage into AI credits.
"""
from __future__ import annotations

from dataclasses import dataclass

from app import pricing
from app.models import AIMode
from app.services.settings_store import Economics

try:  # tiktoken is optional at runtime; fall back to a heuristic.
    import tiktoken

    _ENC = tiktoken.get_encoding("o200k_base")
except Exception:  # pragma: no cover
    _ENC = None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _ENC is not None:
        try:
            return len(_ENC.encode(text))
        except Exception:
            pass
    # ~4 chars per token heuristic
    return max(1, len(text) // 4)


@dataclass
class Estimate:
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_ai_tokens_min: int
    estimated_ai_tokens_max: int
    requires_confirmation: bool


def _charge_for(
    mode: AIMode,
    econ: Economics,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int = 0,
) -> int:
    in_mult = mode.input_token_multiplier or 1.0
    out_mult = mode.output_token_multiplier or 1.0
    reason_mult = mode.reasoning_token_multiplier or 1.0
    billed_usd = pricing.api_cost_usd(
        mode.model,
        int(input_tokens * in_mult),
        int(output_tokens * out_mult),
        int(reasoning_tokens * reason_mult),
    )
    markup = mode.markup_multiplier or econ.global_markup_multiplier
    return pricing.usd_to_ai_tokens(
        billed_usd,
        markup=markup,
        unit_price_usd=econ.token_unit_price_usd,
        base_credit_cost=mode.base_credit_cost or 0,
        min_charge=econ.min_charge_per_request,
        max_charge=econ.max_charge_per_request,
    )


# reasoning-token estimate multipliers per effort level — costs scale
# proportionally with the effort the user picks
EFFORT_FACTORS = {"low": 0.8, "medium": 2.0, "high": 4.0, "xhigh": 6.5}


def estimate(
    mode: AIMode,
    prompt_text: str,
    econ: Economics,
    *,
    context_tokens: int = 0,
    effort_override: str | None = None,
) -> Estimate:
    prompt_tokens = count_tokens(prompt_text)
    est_in = prompt_tokens + context_tokens
    effort = (effort_override or mode.reasoning_effort or "").lower()
    is_reasoning = effort in ("medium", "high", "xhigh")

    est_out_low = max(64, int(est_in * 0.3))
    # Reasoning models legitimately produce page-long answers + hidden
    # reasoning tokens; keep the confirmed upper bound realistic so the
    # cap doesn't eat the platform's margin.
    floor_high = 3000 if is_reasoning else 800
    est_out_high = min(mode.max_output_tokens, max(floor_high, int(est_in * 1.5)))

    reason_low = reason_high = 0
    factor = EFFORT_FACTORS.get(effort, 0.0)
    if factor:
        reason_low = int(est_out_low * factor * 0.4)
        reason_high = int(est_out_high * factor)

    lo = _charge_for(mode, econ, est_in, est_out_low, reason_low)
    hi = _charge_for(mode, econ, est_in, est_out_high, reason_high)
    lo, hi = min(lo, hi), max(lo, hi)

    return Estimate(
        estimated_input_tokens=est_in,
        estimated_output_tokens=est_out_high,
        estimated_ai_tokens_min=lo,
        estimated_ai_tokens_max=hi,
        requires_confirmation=mode.requires_confirmation or hi >= 8,
    )


@dataclass
class Charge:
    api_cost_usd: float
    charged_ai_tokens: int


def compute_charge(
    mode: AIMode,
    econ: Economics,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int = 0,
    *,
    cap: int | None = None,
) -> Charge:
    """Real cost + charged credits. `cap` enforces the confirmed upper bound."""
    real_usd = pricing.api_cost_usd(
        mode.model, input_tokens, output_tokens, reasoning_tokens
    )
    charged = _charge_for(mode, econ, input_tokens, output_tokens, reasoning_tokens)
    if cap is not None:
        charged = min(charged, cap)
    return Charge(api_cost_usd=real_usd, charged_ai_tokens=charged)
