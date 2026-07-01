"""Vector search + metadata filtering (architecture doc Section 9.2; guide Section 10).

Wraps pgvector similarity search behind one interface, so swapping the embedding model or
vector store later (Section 9.1/10.1) doesn't ripple into callers. Testable against the
golden set's expected-chunk annotations without any LLM in the loop (Section 13.1) - this
module makes no LLM calls itself; only rag/embed_documents.embed_query() is used to turn a
raw query into a vector before calling retrieve_chunks().
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import CardDocument, DocumentChunk

# Below this cosine similarity, a chunk is discarded rather than passed downstream (Section
# 10.5) - a low-confidence chunk "just in case" is exactly how ungrounded answers happen.
# Tuned empirically against the golden set (evaluation/rag_eval.py), not by intuition.
DEFAULT_SIMILARITY_THRESHOLD = 0.35
DEFAULT_TOP_K = 5


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    card_name: str
    chunk_text: str
    page_number: int | None
    source_url: str
    effective_date: date
    similarity_score: float


def retrieve_chunks(
    db: Session,
    query_embedding: list[float],
    card_names: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[RetrievedChunk]:
    """Return the top-K most similar chunks, filtered by card ownership and a minimum
    similarity score.

    card_names filtering happens in the same query as the similarity search (Section 10.3),
    never applied only afterward - a multi-card corpus must never let a wrong-card chunk
    outrank a right-card one just because no filter was applied at all.
    """
    cosine_distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(DocumentChunk, CardDocument, (1 - cosine_distance).label("similarity"))
        .join(CardDocument, DocumentChunk.document_id == CardDocument.id)
        .order_by(cosine_distance)
        .limit(top_k)
    )
    if card_names:
        stmt = stmt.where(DocumentChunk.card_name.in_(card_names))

    results = db.execute(stmt).all()

    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            card_name=chunk.card_name,
            chunk_text=chunk.chunk_text,
            page_number=chunk.page_number,
            source_url=document.source_url,
            effective_date=document.effective_date,
            similarity_score=float(similarity),
        )
        for chunk, document, similarity in results
        if similarity >= similarity_threshold
    ]
