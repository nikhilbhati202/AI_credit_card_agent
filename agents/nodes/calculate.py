"""Calculation node (guide Section 14.1): wraps tools/calculator.py via the same
evaluate_card() helper Phase 1's recommendation_service uses - one calculation code path for
both the REST-only Phase 1 flow and the graph, per Section 12.1's dependency direction
(agents/ depends on services/tools/, never duplicates their logic).

Runs for every (spend_item, card) pair - a single_transaction query has one spend_item, a
monthly_optimization query has one per category, so this node naturally handles both without
a special case (Section 14.1: "Tool-level exceptions surface as a validation error, not a
silent default value - a calculation node must never guess a missing input").
"""

from datetime import date
from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session

from agents.state import AgentState, CardResult
from services.recommendation_service import citation_dict, evaluate_card
from tools.retriever import RetrievedChunk


def _rehydrate_chunks(raw: list[dict[str, Any]]) -> list[RetrievedChunk]:
    """state["retrieved_chunks"] is plain dicts (checkpoint-serializable); evaluate_card()
    expects the RetrievedChunk dataclass tools/retriever.py returns - rebuild it here.
    """
    return [
        RetrievedChunk(
            chunk_id=c["chunk_id"],
            card_name=c["card_name"],
            chunk_text=c["chunk_text"],
            page_number=c["page_number"],
            source_url=c["source_url"],
            effective_date=date.fromisoformat(c["effective_date"]),
            similarity_score=c["similarity_score"],
        )
        for c in raw
    ]


def calculate(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db: Session = config["configurable"]["db"]
    cards_owned = state.get("cards_owned", [])
    spend_items = state.get("spend_items", [])
    point_valuation = state.get("point_valuation", 1.0)
    retrieved = _rehydrate_chunks(state.get("retrieved_chunks", []))

    card_results: list[CardResult] = []
    for item in spend_items:
        for card in cards_owned:
            evaluation = evaluate_card(
                db, card, item["category"], item["amount"], point_valuation, retrieved
            )
            if evaluation is None:
                continue
            card_results.append(
                CardResult(
                    card_name=evaluation.card_name,
                    spend_category=item["category"],
                    spend_amount=item["amount"],
                    reward_value=evaluation.reward_value,
                    effective_return_pct=evaluation.effective_return_pct,
                    cap_applied=evaluation.cap_applied,
                    reward_rate=evaluation.reward_rate,
                    reward_unit=evaluation.reward_unit,
                    exclusion_flag=evaluation.exclusion_flag,
                    exclusion_note=evaluation.exclusion_note,
                    confidence_score=evaluation.confidence_score,
                    citation=citation_dict(evaluation) if evaluation.citation else None,
                )
            )

    return {"card_results": card_results}
