"""Deterministic transfer-value calculator (FR-7; architecture doc Section 9.3).

Point transfer is the single highest-stakes, irreversible decision in this domain (Section
1.2) - this tool exists so the transfer-vs-redeem comparison is exact arithmetic, never an
LLM's estimate, matching tools/calculator.py's design discipline exactly. Pure, framework-
agnostic Python with no database or agent-framework imports (Section 5.2).
"""

from dataclasses import dataclass
from typing import Literal

BetterOption = Literal["transfer", "redeem_directly", "equal"]


@dataclass(frozen=True)
class TransferCalculationResult:
    partner_units_received: float
    transfer_value: float  # Rs. value if transferred to the partner and redeemed there
    direct_redemption_value: float  # Rs. value if redeemed directly on the issuer's platform
    value_difference: float  # transfer_value - direct_redemption_value
    better_option: BetterOption


def calculate_transfer_value(
    miles_amount: float,
    transfer_ratio_from: float,
    transfer_ratio_to: float,
    partner_point_valuation: float,
    direct_point_valuation: float = 1.0,
) -> TransferCalculationResult:
    """Compare transferring miles_amount issuer miles/points to a partner program (at the
    given ratio, then valued at partner_point_valuation per partner unit) against redeeming
    them directly on the issuer's own platform (at direct_point_valuation per unit).

    Raises:
        ValueError: for any input that would otherwise force a silent default - never guess
            a missing ratio or valuation (Section 12.2 error-handling policy).
    """
    if miles_amount <= 0:
        raise ValueError("miles_amount must be positive")
    if transfer_ratio_from <= 0 or transfer_ratio_to <= 0:
        raise ValueError("transfer_ratio_from and transfer_ratio_to must be positive")
    if partner_point_valuation <= 0:
        raise ValueError("partner_point_valuation must be positive")
    if direct_point_valuation <= 0:
        raise ValueError("direct_point_valuation must be positive")

    partner_units_received = miles_amount / transfer_ratio_from * transfer_ratio_to
    transfer_value = partner_units_received * partner_point_valuation
    direct_redemption_value = miles_amount * direct_point_valuation
    value_difference = transfer_value - direct_redemption_value

    better_option: BetterOption
    if abs(value_difference) < 0.01:
        better_option = "equal"
    elif value_difference > 0:
        better_option = "transfer"
    else:
        better_option = "redeem_directly"

    return TransferCalculationResult(
        partner_units_received=partner_units_received,
        transfer_value=transfer_value,
        direct_redemption_value=direct_redemption_value,
        value_difference=value_difference,
        better_option=better_option,
    )
