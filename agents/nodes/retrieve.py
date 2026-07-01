"""Retrieval node (guide Section 14.1): wraps tools/retriever.py - no new logic here, this
node's whole job is adapting the graph's state shape to the tool's plain-function signature
(Section 5.2: tools stay framework-agnostic; the adaptation happens in agents/, not tools/).

The database session is injected via LangGraph's per-invocation `config`, never stored in
`state` - state is checkpointed (agents/graph.py's memory saver) and a SQLAlchemy Session
cannot be serialized.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session

from agents.state import AgentState
from rag.embed_documents import embed_query
from tools.retriever import DEFAULT_TOP_K, retrieve_chunks


def retrieve(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db: Session = config["configurable"]["db"]
    query = state["user_query"]
    cards_owned = state.get("cards_owned", [])

    embedding = embed_query(query)
    chunks = retrieve_chunks(db, embedding, card_names=cards_owned, top_k=DEFAULT_TOP_K)

    return {
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
