"""PDF text extraction, cleaning, and normalization (implementation guide, Section 8).

PyMuPDF is the primary extractor (Section 8.1). This module never chunks or embeds - it only
produces clean, per-page text ready for rag/chunk_documents.py.
"""

import re
import unicodedata
from dataclasses import dataclass

import fitz  # PyMuPDF

# Below this ratio of alphanumeric characters to total non-whitespace characters, a page's
# extracted text is treated as garbled (Section 8.6) rather than embedded as-is.
MIN_ALNUM_RATIO = 0.5

# A line repeated on more than this fraction of a document's pages is treated as
# boilerplate (running header/footer) and stripped (Section 8.2).
BOILERPLATE_PAGE_FRACTION = 0.8

# Unicode variants that would otherwise make two semantically identical clauses embed
# differently purely because of surface-text encoding differences (Section 8.3).
_CHAR_REPLACEMENTS = {
    "‘": "'",  # left single quote
    "’": "'",  # right single quote
    "“": '"',  # left double quote
    "”": '"',  # right double quote
    "–": "-",  # en dash
    "—": "-",  # em dash
    " ": " ",  # non-breaking space
    "": "-",  # Wingdings-style bullet glyph (Private Use Area), seen in bank PDFs
    "•": "-",  # standard bullet
}


class NoTextLayerError(Exception):
    """Raised when a PDF has no extractable text (Section 8.6: flag for OCR, never
    silently embed an empty chunk)."""


class GarbledTextError(Exception):
    """Raised when extracted text fails the recognizable-character sanity check (Section 8.6)."""


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-indexed, matching how a human would cite "page 3"
    text: str


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans(_CHAR_REPLACEMENTS))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _alnum_ratio(text: str) -> float:
    stripped = re.sub(r"\s", "", text)
    if not stripped:
        return 0.0
    alnum = sum(1 for c in stripped if c.isalnum())
    return alnum / len(stripped)


def _strip_boilerplate(pages: list[str]) -> list[str]:
    """Detect lines repeated near-identically across most pages (page numbers, running
    'Terms and Conditions vX.Y' footers) and remove them (Section 8.2).
    """
    if len(pages) < 3:
        return pages

    line_counts: dict[str, int] = {}
    for page in pages:
        for line in {line.strip() for line in page.splitlines() if line.strip()}:
            line_counts[line] = line_counts.get(line, 0) + 1

    threshold = len(pages) * BOILERPLATE_PAGE_FRACTION
    boilerplate = {line for line, count in line_counts.items() if count >= threshold}
    if not boilerplate:
        return pages

    cleaned = []
    for page in pages:
        kept_lines = [line for line in page.splitlines() if line.strip() not in boilerplate]
        cleaned.append("\n".join(kept_lines))
    return cleaned


def extract_pdf_pages(pdf_path: str) -> list[PageText]:
    """Extract, clean, and normalize text from every page of a PDF.

    Raises:
        NoTextLayerError: if the document has no extractable text on any page - a scanned
            PDF must be flagged for OCR (Section 8.6), never silently ingested empty.
        GarbledTextError: if the extracted text fails the recognizable-character sanity check.
    """
    doc = fitz.open(pdf_path)
    try:
        raw_pages = [page.get_text() for page in doc]
    finally:
        doc.close()

    if not raw_pages or all(not text.strip() for text in raw_pages):
        raise NoTextLayerError(
            f"{pdf_path}: no extractable text on any page - flag for OCR, do not ingest."
        )

    deboilerplated = _strip_boilerplate(raw_pages)
    pages = [PageText(page_number=i + 1, text=_normalize(t)) for i, t in enumerate(deboilerplated)]

    full_text = "\n".join(p.text for p in pages)
    ratio = _alnum_ratio(full_text)
    if ratio < MIN_ALNUM_RATIO:
        raise GarbledTextError(
            f"{pdf_path}: alnum ratio {ratio:.2f} below threshold {MIN_ALNUM_RATIO} - "
            "extraction likely produced garbled text; reject rather than embed."
        )

    return [p for p in pages if p.text]
