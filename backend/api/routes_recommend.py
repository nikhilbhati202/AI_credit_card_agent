"""POST /recommend (architecture doc Section 13). First endpoint built after /health per the
implementation guide, Section 16: highest-value, highest-risk endpoint, built right after the
trivial health check.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.db import get_db
from services.recommendation_service import RecommendationInputError, recommend

router = APIRouter(prefix="/api/v1", tags=["recommend"])


class RecommendRequest(BaseModel):
    query: str = Field(..., min_length=1, examples=["I am spending Rs. 50,000 on flights."])
    cards_owned: list[str] = Field(..., min_length=1)
    point_valuation: float = Field(default=1.0, gt=0)


class RecommendResponse(BaseModel):
    spend_amount: float
    spend_category: str | None
    recommended_card: str | None
    estimated_reward_value: float | None
    effective_return_pct: float | None
    calculation: dict[str, Any] | None
    rules_used: list[dict[str, Any]]
    caps_or_exclusions: list[str]
    assumptions: list[str]
    alternatives: list[dict[str, Any]]
    confidence: str | None
    insufficient_information: bool
    message: str | None


@router.post("/recommend", response_model=RecommendResponse)
def post_recommend(request: RecommendRequest, db: Session = Depends(get_db)) -> RecommendResponse:
    """Domain refusals (insufficient evidence) are a normal 200 response, not an error
    (Section 12.2). Only malformed input reaches RecommendationInputError -> 422, raised by
    FastAPI's exception handling (Section 16's consistent error envelope, registered in
    backend/main.py).
    """
    try:
        result = recommend(
            db=db,
            query=request.query,
            cards_owned=request.cards_owned,
            point_valuation=request.point_valuation,
        )
    except RecommendationInputError as exc:
        raise HTTPException(
            status_code=422, detail={"error": {"code": "validation_error", "message": str(exc)}}
        ) from exc

    return RecommendResponse(**result.__dict__)
