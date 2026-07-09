"""POST /optimize/monthly (architecture doc Section 13; guide Section 3 Phase 2: monthly
spend optimization use case). Runs the same compiled graph as /recommend - Intent
Classification determines this is a monthly_optimization query from the free-text
description (a list of category+amount pairs), and Calculation/Comparison run once per
category, exactly like /recommend runs once for its single category.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agents.llm import LLMNotConfiguredError, LLMUnavailableError
from agents.runner import get_pending_interrupt, run_agent
from database.db import get_db
from monitoring.custom_logger import log_recommendation, timed_request

router = APIRouter(prefix="/api/v1", tags=["optimize"])


class MonthlyOptimizeRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        examples=[
            "My monthly spend is about 20000 on groceries, 15000 on dining, "
            "10000 on fuel, and 8000 on utility bills. How should I split this?"
        ],
    )
    cards_owned: list[str] = Field(
        ..., min_length=3, description="At least 3 cards, per the Phase 2 acceptance criterion"
    )
    point_valuation: float = Field(default=1.0, gt=0)
    session_id: str | None = None


class MonthlyOptimizeResponse(BaseModel):
    session_id: str
    follow_up_question: str | None = None
    approval_pending: bool = False
    transfer_proposal: dict[str, Any] | None = None
    insufficient_information: bool = False
    allocation: list[dict[str, Any]] = Field(default_factory=list)
    total_estimated_reward_value: float | None = None
    assumptions: list[str] = Field(default_factory=list)
    message: str | None = None
    explanation: str | None = None


@router.post("/optimize/monthly", response_model=MonthlyOptimizeResponse)
def post_optimize_monthly(
    request: MonthlyOptimizeRequest, db: Session = Depends(get_db)
) -> MonthlyOptimizeResponse:
    with timed_request() as timing:
        try:
            state, session_id = run_agent(
                db=db,
                query=request.query,
                cards_owned=request.cards_owned,
                point_valuation=request.point_valuation,
                session_id=request.session_id,
            )
        except LLMNotConfiguredError as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": {"code": "llm_not_configured", "message": str(exc)}},
            ) from exc
        except LLMUnavailableError as exc:
            raise HTTPException(
                status_code=503, detail={"error": {"code": "llm_unavailable", "message": str(exc)}}
            ) from exc

        final_answer = state.get("final_answer")
        interrupt_payload = get_pending_interrupt(state)
        if interrupt_payload is not None:
            response = MonthlyOptimizeResponse(
                session_id=session_id,
                approval_pending=True,
                transfer_proposal=interrupt_payload.get("proposal"),
            )
        elif state.get("follow_up_question"):
            response = MonthlyOptimizeResponse(
                session_id=session_id, follow_up_question=state["follow_up_question"]
            )
        else:
            response = MonthlyOptimizeResponse.model_validate(
                {"session_id": session_id, **(final_answer or {})}
            )

    log_recommendation(
        db,
        user_id=None,
        query=request.query,
        intent=state.get("intent"),
        retrieved_chunk_ids=[int(c["chunk_id"]) for c in state.get("retrieved_chunks", [])],
        final_answer=final_answer,
        latency_ms=timing["latency_ms"],
        confidence=None,
    )
    return response
