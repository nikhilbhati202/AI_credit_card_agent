"""Chunking with metadata attachment (implementation guide, Section 8.4-8.5).

Phase 1 baseline per Section 8.4: recursive character splitting (~400-600 tokens,
~50-token overlap), approximated here as characters (~4 chars/token) since the embedding
model (local, sentence-transformers) has no meaningful "official" tokenizer to split by -
unlike OpenAI's tiktoken, byte-pair boundaries for BGE/MiniLM aren't a stable public
contract to split on. Structure-aware chunking (clause/heading boundaries) is an explicit
Phase 2 improvement (Section 8.4), not a Phase 1 requirement.

Known Phase 1 limitation: chunking runs per-page, so a rule spanning a page break can be
split across two chunks. Section 8.4 flags this as the reason to move to structure-aware
chunking once golden-set evaluation exposes a specific failure - not before.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.ingest_pdfs import PageText

CHUNK_SIZE_CHARS = 2000  # ~500 tokens at ~4 chars/token, within the guide's 400-600 range
CHUNK_OVERLAP_CHARS = 200  # ~50 tokens


@dataclass(frozen=True)
class ChunkMetadata:
    card_name: str
    issuer: str
    document_type: str
    effective_date: date
    source_url: str


@dataclass(frozen=True)
class Chunk:
    text: str
    page_number: int
    metadata: ChunkMetadata = field(repr=False)


def chunk_pages(pages: list[PageText], metadata: ChunkMetadata) -> list[Chunk]:
    """Split cleaned page text into overlapping chunks, attaching metadata at chunk time
    (Section 8.5) rather than deferring it to query time.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE_CHARS,
        chunk_overlap=CHUNK_OVERLAP_CHARS,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[Chunk] = []
    for page in pages:
        if not page.text.strip():
            continue
        for piece in splitter.split_text(page.text):
            if piece.strip():
                chunks.append(Chunk(text=piece, page_number=page.page_number, metadata=metadata))
    return chunks


def chunk_metadata_json(metadata: ChunkMetadata, embedding_model_version: str) -> dict[str, Any]:
    """The document_chunks.metadata_json payload: embedding model/version (Section 9.2) plus
    the source attribution needed for citation, duplicated here so it survives independent of
    the card_documents join for cheap read paths.
    """
    return {
        "issuer": metadata.issuer,
        "document_type": metadata.document_type,
        "effective_date": metadata.effective_date.isoformat(),
        "source_url": metadata.source_url,
        "embedding_model_version": embedding_model_version,
    }
