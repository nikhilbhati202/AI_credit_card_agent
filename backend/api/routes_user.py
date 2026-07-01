"""GET/PUT /user/profile (architecture doc Section 13; guide Section 16 endpoint order).

No auth token required yet - see services/user_profile_service.py's docstring for why that's
an intentional, staged decision rather than an oversight.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from services.user_profile_service import get_profile, upsert_profile

router = APIRouter(prefix="/api/v1", tags=["user"])


class UserProfileResponse(BaseModel):
    user_id: str
    cards_owned: list[str]
    preferences: dict[str, Any]
    conversation_summary: str | None


class UserProfileUpdateRequest(BaseModel):
    user_id: str
    cards_owned: list[str] | None = None
    preferences: dict[str, Any] | None = None


@router.get("/user/profile", response_model=UserProfileResponse)
def read_user_profile(user_id: str, db: Session = Depends(get_db)) -> UserProfileResponse:
    profile = get_profile(db, user_id)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {"code": "not_found", "message": f"No profile for user_id={user_id!r}"}
            },
        )
    return UserProfileResponse(
        user_id=profile.user_id,
        cards_owned=profile.cards_owned,
        preferences=profile.preferences,
        conversation_summary=profile.conversation_summary,
    )


@router.put("/user/profile", response_model=UserProfileResponse)
def update_user_profile(
    request: UserProfileUpdateRequest, db: Session = Depends(get_db)
) -> UserProfileResponse:
    profile = upsert_profile(
        db, request.user_id, cards_owned=request.cards_owned, preferences=request.preferences
    )
    return UserProfileResponse(
        user_id=profile.user_id,
        cards_owned=profile.cards_owned,
        preferences=profile.preferences,
        conversation_summary=profile.conversation_summary,
    )
