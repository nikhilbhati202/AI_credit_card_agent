"""User profile persistence (FR-1, FR-8; guide Section 3 Phase 2 deliverable: user_profiles
table actually used, not just present in the schema).

No password/JWT auth here - FR-1 explicitly scopes real authentication to "once there's a
real multi-user concern" (Section 12.1), which a capstone-scale Phase 2 doesn't yet have.
`user_id` is a caller-supplied identifier only; adding real auth later only touches how
`user_id` is established, not this service.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import UserProfile


def get_profile(db: Session, user_id: str) -> UserProfile | None:
    return db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalar_one_or_none()


def upsert_profile(
    db: Session,
    user_id: str,
    cards_owned: list[str] | None = None,
    preferences: dict[str, Any] | None = None,
) -> UserProfile:
    profile = get_profile(db, user_id)
    if profile is None:
        profile = UserProfile(
            user_id=user_id,
            cards_owned=cards_owned or [],
            preferences=preferences or {},
        )
        db.add(profile)
    else:
        if cards_owned is not None:
            profile.cards_owned = cards_owned
        if preferences is not None:
            profile.preferences = preferences
    db.commit()
    db.refresh(profile)
    return profile
