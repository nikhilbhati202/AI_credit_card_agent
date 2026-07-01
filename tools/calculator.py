"""Deterministic reward-value calculator (FR-4; architecture doc Section 9.1).

This is the single most important reliability boundary in the system: the LLM is never
trusted to do this arithmetic (Section 1.2). This module is pure, framework-agnostic Python
with no database or agent-framework imports (Section 5.2), so it is unit-testable in total
isolation and reusable from a batch evaluation script or any future interface.

Unification note: reward_rate is always "reward units earned per Rs.100 spent." For
reward_unit=CASHBACK, 1 unit is worth exactly Rs.1 by definition, so a rate of "5" means both
"5% of spend" and "5 units per Rs.100" - the same number. For POINTS/MILES, a unit's Rs. value
is not a fact the issuer states (it's an assumption the caller supplies via point_valuation,
per FR-6) - so cashback and points/miles share one code path up to the final Rs.-value step.
"""

import enum
from dataclasses import dataclass


class RewardUnit(enum.StrEnum):
    POINTS = "points"
    MILES = "miles"
    CASHBACK = "cashback"


class CapBasis(enum.StrEnum):
    """What cap_value is measured in.

    SPEND: the accelerated rate applies only up to this much spend; amount beyond it earns
        excess_reward_rate instead (e.g. Axis Atlas: 5x up to Rs.2L spend/month, 2x beyond).
    REWARD_UNITS: the accelerated rate applies until this many reward units (or Rs. of
        cashback) have been earned, regardless of how much spend that took (e.g. SBI
        Cashback: 5% online capped at Rs.2,000 cashback/month).
    """

    SPEND = "spend"
    REWARD_UNITS = "reward_units"


@dataclass(frozen=True)
class RewardCalculationResult:
    base_reward_units: float  # points/miles earned, or Rs. of cashback
    reward_value: float  # Rs. value of the reward (== base_reward_units for CASHBACK)
    effective_return_pct: float  # reward_value / spend_amount * 100
    cap_applied: bool
    milestone_triggered: bool


def calculate_reward(
    spend_amount: float,
    reward_rate: float,
    reward_unit: RewardUnit,
    cap_basis: CapBasis | None = None,
    cap_value: float | None = None,
    excess_reward_rate: float = 0.0,
    point_valuation: float = 1.0,
    milestone_thresholds: list[float] | None = None,
) -> RewardCalculationResult:
    """Compute the reward value of a single transaction against a single reward rule.

    Assumes this transaction is the only spend so far in the cap's reset period (an explicit,
    surfaced assumption - see Section 13's "Monthly cap assumed unused" example) since Phase 1
    has no cumulative multi-transaction spend ledger (architecture doc Section 9.1 edge cases).

    Raises:
        ValueError: for any input that would otherwise force a silent default - a missing or
            invalid input must fail loudly, never guess (Section 12.2 error-handling policy).
    """
    if spend_amount <= 0:
        raise ValueError("spend_amount must be positive")
    if reward_rate < 0:
        raise ValueError("reward_rate cannot be negative")
    if excess_reward_rate < 0:
        raise ValueError("excess_reward_rate cannot be negative")
    if point_valuation <= 0:
        raise ValueError("point_valuation must be positive")
    if (cap_basis is None) != (cap_value is None):
        raise ValueError("cap_basis and cap_value must be provided together")
    if cap_value is not None and cap_value <= 0:
        raise ValueError("cap_value must be positive")

    cap_applied = False
    if cap_basis is None:
        base_reward_units = spend_amount / 100 * reward_rate
    elif cap_basis == CapBasis.SPEND:
        assert cap_value is not None
        eligible_spend = min(spend_amount, cap_value)
        excess_spend = max(spend_amount - cap_value, 0.0)
        base_reward_units = (
            eligible_spend / 100 * reward_rate + excess_spend / 100 * excess_reward_rate
        )
        cap_applied = spend_amount > cap_value
    else:  # CapBasis.REWARD_UNITS
        assert cap_value is not None
        if reward_rate == 0:
            raise ValueError("reward_rate must be positive to apply a reward_units cap")
        uncapped_units = spend_amount / 100 * reward_rate
        # Spend at which the base rate alone would reach the reward-unit cap.
        spend_threshold = cap_value / reward_rate * 100
        eligible_spend = min(spend_amount, spend_threshold)
        excess_spend = max(spend_amount - spend_threshold, 0.0)
        base_reward_units = (
            eligible_spend / 100 * reward_rate + excess_spend / 100 * excess_reward_rate
        )
        cap_applied = uncapped_units > cap_value

    reward_value = (
        base_reward_units
        if reward_unit == RewardUnit.CASHBACK
        else base_reward_units * point_valuation
    )
    effective_return_pct = reward_value / spend_amount * 100
    milestone_triggered = bool(milestone_thresholds) and spend_amount >= min(
        milestone_thresholds or [float("inf")]
    )

    return RewardCalculationResult(
        base_reward_units=base_reward_units,
        reward_value=reward_value,
        effective_return_pct=effective_return_pct,
        cap_applied=cap_applied,
        milestone_triggered=milestone_triggered,
    )
