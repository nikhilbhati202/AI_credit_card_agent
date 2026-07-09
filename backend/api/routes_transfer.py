"""POST /transfer/evaluate and POST /transfer/confirm (architecture doc Section 13; guide
Section 3 Phase 3: "Transfer Strategy" vertical slice).

/transfer/evaluate runs the same compiled graph as /recommend, but a transfer_evaluation
query pauses at Human Approval (agents/nodes/approval.py's real LangGraph interrupt) instead
of reaching a final answer - this endpoint reports that paused proposal back to the caller
without ever finalizing it (Section 3's acceptance criterion: "no transfer calculation ever
finalized without explicit approval observed in a trace").

/transfer/confirm is the only way to resume that paused execution: the caller passes back the
session_id and an approved/rejected decision, and agents/runner.py's resume_agent() sends a
real Command(resume=...) into the SAME paused execution (never a fresh run from START).
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agents.llm import LLMNotConfiguredError, LLMUnavailableError
from agents.runner import get_pending_interrupt, has_pending_approval, resume_agent, run_agent
from database.db import get_db
from monitoring.custom_logger import log_recommendation, timed_request

router = APIRouter(prefix="/api/v1/transfer", tags=["transfer"])

TransferEvaluateStatus = Literal["pending_approval", "clarification_needed", "refused", "completed"]


class TransferEvaluateRequest(BaseModel):
    query: str = Field(
        ..., min_length=1, examples=["Should I transfer 10000 miles to Singapore KrisFlyer?"]
    )
    cards_owned: list[str] = Field(..., min_length=1)
    point_valuation: float = Field(default=1.0, gt=0)
    session_id: str | None = Field(
        default=None,
        description="Reuse the session_id from a prior response to continue a conversation.",
    )


class TransferEvaluateResponse(BaseModel):
    session_id: str
    status: TransferEvaluateStatus
    follow_up_question: str | None = None
    proposal: dict[str, Any] | None = None
    message: str | None = None


class TransferConfirmRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    approved: bool


class TransferConfirmResponse(BaseModel):
    session_id: str
    approval_status: Literal["approved", "rejected"]
    transfer_proposal: dict[str, Any] | None = None
    message: str | None = None


@router.post("/evaluate", response_model=TransferEvaluateResponse)
def post_transfer_evaluate(
    request: TransferEvaluateRequest, db: Session = Depends(get_db)
) -> TransferEvaluateResponse:
    """A session with a still-open approval must be resolved via /transfer/confirm first
    (Section 13) - evaluating it again would invoke the graph from START on a thread that is
    paused mid-execution, which LangGraph does not support.
    """
    if request.session_id and has_pending_approval(db, request.session_id):
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "approval_pending",
                    "message": (
                        f"session_id={request.session_id!r} has a transfer awaiting approval; "
                        "call /transfer/confirm before evaluating a new request on it."
                    ),
                }
            },
        )

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

        interrupt_payload = get_pending_interrupt(state)
        final_answer = state.get("final_answer")
        follow_up_question = state.get("follow_up_question")

        if interrupt_payload is not None:
            status: TransferEvaluateStatus = "pending_approval"
            proposal = interrupt_payload.get("proposal")
            message = None
        elif follow_up_question:
            status = "clarification_needed"
            proposal = None
            message = None
        elif final_answer and final_answer.get("insufficient_information"):
            status = "refused"
            proposal = None
            message = final_answer.get("message")
        else:
            status = "completed"
            proposal = (final_answer or {}).get("transfer_proposal")
            message = (final_answer or {}).get("message")

        response = TransferEvaluateResponse(
            session_id=session_id,
            status=status,
            follow_up_question=follow_up_question,
            proposal=proposal,
            message=message,
        )

    log_recommendation(
        db,
        user_id=None,
        query=request.query,
        intent=state.get("intent"),
        retrieved_chunk_ids=[],
        final_answer=final_answer,
        latency_ms=timing["latency_ms"],
        confidence=None,
    )
    return response


@router.post("/confirm", response_model=TransferConfirmResponse)
def post_transfer_confirm(
    request: TransferConfirmRequest, db: Session = Depends(get_db)
) -> TransferConfirmResponse:
    """Resumes a paused Human Approval interrupt - the only code path that can turn a
    transfer proposal into a finalized (or explicitly cancelled) result (Section 3's
    acceptance criterion).
    """
    try:
        result = resume_agent(db, request.session_id, request.approved)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "no_pending_approval", "message": str(exc)}},
        ) from exc
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "llm_not_configured", "message": str(exc)}},
        ) from exc
    except LLMUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail={"error": {"code": "llm_unavailable", "message": str(exc)}}
        ) from exc

    final_answer = result.get("final_answer") or {}
    approval_status_raw = result.get("approval_status")
    if approval_status_raw not in ("approved", "rejected"):
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "internal_error",
                    "message": "resume did not produce an approved/rejected approval_status",
                }
            },
        )
    approval_status: Literal["approved", "rejected"] = approval_status_raw
    return TransferConfirmResponse(
        session_id=request.session_id,
        approval_status=approval_status,
        transfer_proposal=final_answer.get("transfer_proposal"),
        message=final_answer.get("message"),
    )
