"""Transfer-evaluation service (FR-7): composes the transfer_partners repository lookup
with tools/transfer_calculator.py, the same pattern recommendation_service.py uses for
single-transaction recommendations (Section 12.1 step 5).
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import TransferPartner
from tools.transfer_calculator import calculate_transfer_value

DEFAULT_DIRECT_POINT_VALUATION = 1.0


class TransferPartnerNotFoundError(ValueError):
    """Raised when the requested card+partner combination has no known transfer ratio -
    Section 12.2's validation-error class, never a guessed ratio.
    """


@dataclass(frozen=True)
class TransferProposal:
    card_name: str
    partner_name: str
    miles_amount: float
    transfer_ratio_from: float
    transfer_ratio_to: float
    partner_units_received: float
    transfer_value: float
    direct_redemption_value: float
    value_difference: float
    better_option: str
    confidence_score: float
    source_note: str | None


def get_transfer_partner(db: Session, card_name: str, partner_name: str) -> TransferPartner | None:
    return db.execute(
        select(TransferPartner).where(
            TransferPartner.card_name == card_name, TransferPartner.partner_name == partner_name
        )
    ).scalar_one_or_none()


def evaluate_transfer(
    db: Session,
    card_name: str,
    partner_name: str,
    miles_amount: float,
    partner_point_valuation: float,
    direct_point_valuation: float = DEFAULT_DIRECT_POINT_VALUATION,
) -> TransferProposal:
    """Raises TransferPartnerNotFoundError if the card+partner combination is unknown."""
    partner = get_transfer_partner(db, card_name, partner_name)
    if partner is None:
        raise TransferPartnerNotFoundError(
            f"No known transfer ratio for {card_name!r} -> {partner_name!r}"
        )

    result = calculate_transfer_value(
        miles_amount=miles_amount,
        transfer_ratio_from=partner.transfer_ratio_from,
        transfer_ratio_to=partner.transfer_ratio_to,
        partner_point_valuation=partner_point_valuation,
        direct_point_valuation=direct_point_valuation,
    )

    return TransferProposal(
        card_name=card_name,
        partner_name=partner_name,
        miles_amount=miles_amount,
        transfer_ratio_from=partner.transfer_ratio_from,
        transfer_ratio_to=partner.transfer_ratio_to,
        partner_units_received=result.partner_units_received,
        transfer_value=result.transfer_value,
        direct_redemption_value=result.direct_redemption_value,
        value_difference=result.value_difference,
        better_option=result.better_option,
        confidence_score=partner.confidence_score,
        source_note=partner.source_note,
    )


def proposal_dict(proposal: TransferProposal) -> dict[str, Any]:
    return {
        "card_name": proposal.card_name,
        "partner_name": proposal.partner_name,
        "miles_amount": proposal.miles_amount,
        "transfer_ratio": f"{proposal.transfer_ratio_from}:{proposal.transfer_ratio_to}",
        "partner_units_received": round(proposal.partner_units_received, 2),
        "transfer_value": round(proposal.transfer_value, 2),
        "direct_redemption_value": round(proposal.direct_redemption_value, 2),
        "value_difference": round(proposal.value_difference, 2),
        "better_option": proposal.better_option,
        "confidence_score": proposal.confidence_score,
        "source_note": proposal.source_note,
    }
