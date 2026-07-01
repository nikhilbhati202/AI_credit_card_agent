"""Local embedding generation (implementation guide, Section 9).

Uses a local, open-source model (Section 9.1's zero-cost/privacy option) rather than an
OpenAI API key, per this phase's setup. The retriever (tools/retriever.py) only depends on
embed_query() below, so swapping the model later is the "contained, well-isolated change"
Section 9.1 describes - not a rewrite of retrieval logic.
"""

import hashlib

from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_MODEL_VERSION = "bge-small-en-v1.5"  # stored per-chunk (Section 9.2); bump if the
# model is ever swapped, since distances are not comparable across models.

# BGE's documented convention: prepend this instruction to *queries* only, never to the
# passages/chunks being searched - asymmetric instruction tuning is how the model was trained.
_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Batch-embed chunk texts for storage (Section 9.3: batch calls, never one-by-one)."""
    if not texts:
        return []
    vectors = _get_model().encode(
        texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    """Embed a single user query at request time (Section 9.2: only the query is embedded
    inline; ingestion-time content is always embedded in the batch script above).
    """
    vector = _get_model().encode(_QUERY_INSTRUCTION + text, convert_to_numpy=True)
    return [float(x) for x in vector]


def content_hash(chunk_text: str, model_version: str = EMBEDDING_MODEL_VERSION) -> str:
    """Cache key for (chunk_text + model_version) (Section 9.2), so re-running ingestion
    after an unrelated code change doesn't re-embed unchanged chunks.
    """
    return hashlib.sha256(f"{model_version}:{chunk_text}".encode()).hexdigest()
