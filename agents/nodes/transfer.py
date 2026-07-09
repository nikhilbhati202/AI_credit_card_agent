"""Transfer proposal node (FR-7; guide Section 9.3) - the deterministic computation behind
a transfer_evaluation query. No LLM involved: looks up the card+partner ratio and runs
tools/transfer_calculator.py, exactly like Calculation does for spend recommendations.

The proposal this node builds is what the Human Approval node (agents/nodes/approval.py)
presents to the user before anything is finalized - FR-13's core requirement that no
transfer calculation is ever finalized without an explicit approval step.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session

from agents.state import AgentState
from services.transfer_service import (
    TransferPartnerNotFoundError,
    evaluate_transfer,
    proposal_dict,
)

DEFAULT_PARTNER_POINT_VALUATION = 1.0


def propose_transfer(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db: Session = config["configurable"]["db"]
    cards_owned = state.get("cards_owned", [])
    request = state.get("transfer_request", {})
    partner_name = request.get("partner_name")
    miles_amount = request.get("miles_amount")
    partner_point_valuation = (
        request.get("partner_point_valuation") or DEFAULT_PARTNER_POINT_VALUATION
    )

    if not isinstance(partner_name, str) or not isinstance(miles_amount, int | float):
        return {
            "evidence_sufficient": False,
            "evidence_reason": "Missing a transfer partner name or miles amount to evaluate.",
        }
    partner_name_str = partner_name
    miles_amount_float = float(miles_amount)
    partner_point_valuation_float = float(
        partner_point_valuation
        if isinstance(partner_point_valuation, int | float)
        else DEFAULT_PARTNER_POINT_VALUATION
    )

    proposal = None
    for card_name in cards_owned:
        try:
            proposal = evaluate_transfer(
                db,
                card_name,
                partner_name_str,
                miles_amount_float,
                partner_point_valuation_float,
            )
            break
        except TransferPartnerNotFoundError:
            continue

    if proposal is None:
        return {
            "evidence_sufficient": False,
            "evidence_reason": (
                f"None of your owned cards ({', '.join(cards_owned)}) have a known transfer "
                f"ratio to {partner_name!r}."
            ),
        }

    return {
        "evidence_sufficient": True,
        "evidence_reason": "ok",
        "transfer_proposal": proposal_dict(proposal),
    }
