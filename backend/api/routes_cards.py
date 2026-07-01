"""GET /cards (architecture doc Section 13): list cards known to the system, so a UI/client
can populate a cards_owned picker without hardcoding the seeded card list.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import CardDocument

router = APIRouter(prefix="/api/v1", tags=["cards"])


class CardSummary(BaseModel):
    card_name: str
    issuer: str
    effective_date: str


@router.get("/cards", response_model=list[CardSummary])
def list_cards(db: Session = Depends(get_db)) -> list[CardSummary]:
    documents = db.execute(
        select(CardDocument).order_by(CardDocument.issuer, CardDocument.card_name)
    ).scalars()
    return [
        CardSummary(
            card_name=doc.card_name,
            issuer=doc.issuer,
            effective_date=doc.effective_date.isoformat(),
        )
        for doc in documents
    ]
