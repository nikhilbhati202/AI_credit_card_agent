"""Retrieval node (guide Section 14.1): wraps tools/retriever.py - no new logic here, this
node's whole job is adapting the graph's state shape to the tool's plain-function signature
(Section 5.2: tools stay framework-agnostic; the adaptation happens in agents/, not tools/).

The database session is injected via LangGraph's per-invocation `config`, never stored in
`state` - state is checkpointed (agents/graph.py's memory saver) and a SQLAlchemy Session
cannot be serialized.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.state import AgentState
from database.models import CardDocument
from rag.embed_documents import embed_query
from tools.retriever import DEFAULT_TOP_K, retrieve_chunks


def _unrecognized_cards(db: Session, cards_owned: list[str]) -> list[str]:
    """Which of cards_owned don't match any seeded card at all - an exact-string-match
    typo/casing mismatch (e.g. "axis atlas" or "Axis Atlas ") is otherwise indistinguishable
    from "this card genuinely has no evidence for this query," and Rule Validation's generic
    refusal message left a user with no way to tell the two apart.
    """
    if not cards_owned:
        return []
    known = set(
        db.execute(
            select(CardDocument.card_name).where(CardDocument.card_name.in_(cards_owned))
        ).scalars()
    )
    return [c for c in cards_owned if c not in known]


def retrieve(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db: Session = config["configurable"]["db"]
    query = state["user_query"]
    cards_owned = state.get("cards_owned", [])

    embedding = embed_query(query)
    chunks = retrieve_chunks(db, embedding, card_names=cards_owned, top_k=DEFAULT_TOP_K)

    result: dict[str, Any] = {
        "retrieved_chunks": [
            {
                "chunk_id": c.chunk_id,
                "card_name": c.card_name,
                "chunk_text": c.chunk_text,
                "page_number": c.page_number,
                "source_url": c.source_url,
                "effective_date": c.effective_date.isoformat(),
                "similarity_score": c.similarity_score,
            }
            for c in chunks
        ]
    }
    if not chunks:
        result["unrecognized_cards"] = _unrecognized_cards(db, cards_owned)
    return result
