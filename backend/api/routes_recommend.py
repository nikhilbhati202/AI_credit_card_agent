"""POST /recommend (architecture doc Section 13). Runs the LangGraph agent (guide Section 3
Phase 2: "Replace the single-shot pipeline with a LangGraph agent") rather than calling
services/recommendation_service.py directly - Phase 1's service logic is still there, reused
inside agents/nodes/calculate.py's evaluate_card() call, just orchestrated by the graph now.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agents.llm import LLMNotConfiguredError, LLMUnavailableError
from agents.runner import get_pending_interrupt, run_agent
from database.db import get_db
from monitoring.custom_logger import log_recommendation, timed_request

router = APIRouter(prefix="/api/v1", tags=["recommend"])


class RecommendRequest(BaseModel):
    query: str = Field(..., min_length=1, examples=["I am spending Rs. 50,000 on flights."])
    cards_owned: list[str] = Field(..., min_length=1)
    point_valuation: float = Field(default=1.0, gt=0)
    session_id: str | None = Field(
        default=None,
        description="Reuse the session_id from a prior response to continue a conversation.",
    )


class RecommendResponse(BaseModel):
    session_id: str
    follow_up_question: str | None = None
    approval_pending: bool = False
    transfer_proposal: dict[str, Any] | None = None
    spend_category: str | None = None
    recommended_card: str | None = None
    estimated_reward_value: float | None = None
    effective_return_pct: float | None = None
    calculation: dict[str, Any] | None = None
    rules_used: list[dict[str, Any]] = Field(default_factory=list)
    caps_or_exclusions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str | None = None
    insufficient_information: bool = False
    message: str | None = None
    explanation: str | None = None


@router.post("/recommend", response_model=RecommendResponse)
def post_recommend(request: RecommendRequest, db: Session = Depends(get_db)) -> RecommendResponse:
    """Domain refusals (insufficient evidence) are a normal 200 response, not an error
    (Section 12.2). LLM configuration/availability failures map to 503 (Section 14.1: never
    silently default to a guessed output when the LLM is unreachable).
    """
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
            # A transfer-shaped query reached Human Approval (Section 10.11) even though the
            # caller used the general /recommend endpoint - surface the pause rather than
            # returning an empty-looking response, so a single chat UI can drive every intent
            # through this one endpoint and use /transfer/confirm to resolve the gate.
            response = RecommendResponse(
                session_id=session_id,
                approval_pending=True,
                transfer_proposal=interrupt_payload.get("proposal"),
            )
        elif state.get("follow_up_question"):
            response = RecommendResponse(
                session_id=session_id, follow_up_question=state["follow_up_question"]
            )
        else:
            response = RecommendResponse.model_validate(
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
        confidence=response.confidence,
    )
    return response
