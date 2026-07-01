"""Retrieval precision@K against the golden set (architecture doc Section 20; guide Section
18.2). Phase 1 acceptance criterion: precision@5 >= 0.75 (architecture doc Section 3.6).

Run directly:
    .venv/Scripts/python -m evaluation.rag_eval
"""

import sys
from dataclasses import dataclass

from database.db import SessionLocal
from evaluation.golden_dataset import GoldenCase, load_golden_cases
from rag.embed_documents import embed_query
from tools.retriever import DEFAULT_TOP_K, retrieve_chunks

# Only cases with a single, unambiguous expected card have a well-defined "relevant chunk"
# card to score against; none_reward/insufficient_information cases don't name one winner.
_SCORABLE_OUTCOMES = {"recommended"}


@dataclass(frozen=True)
class CasePrecision:
    case: GoldenCase
    retrieved_count: int
    relevant_count: int

    @property
    def precision(self) -> float:
        if self.retrieved_count == 0:
            return 0.0
        return self.relevant_count / self.retrieved_count


def _score_case(case: GoldenCase, top_k: int) -> CasePrecision:
    db = SessionLocal()
    try:
        embedding = embed_query(case.query)
        retrieved = retrieve_chunks(
            db, embedding, card_names=case.cards_owned, top_k=top_k, similarity_threshold=0.0
        )
    finally:
        db.close()

    relevant = sum(1 for chunk in retrieved if chunk.card_name == case.expected_recommended_card)
    return CasePrecision(case=case, retrieved_count=len(retrieved), relevant_count=relevant)


def run(top_k: int = DEFAULT_TOP_K) -> list[CasePrecision]:
    scorable = [c for c in load_golden_cases() if c.expected_outcome in _SCORABLE_OUTCOMES]
    return [_score_case(c, top_k) for c in scorable]


def main() -> int:
    results = run()
    for r in results:
        print(
            f"#{r.case.id}: {r.case.query!r} -> precision@{DEFAULT_TOP_K}={r.precision:.2f} "
            f"({r.relevant_count}/{r.retrieved_count} relevant to "
            f"{r.case.expected_recommended_card!r})"
        )

    mean_precision = sum(r.precision for r in results) / len(results) if results else 0.0
    print(
        f"\nMean precision@{DEFAULT_TOP_K}: {mean_precision:.3f} over {len(results)} scorable cases"
    )

    threshold = 0.75
    if mean_precision < threshold:
        print(f"FAILED: below the Phase 1 acceptance threshold of {threshold}.")
        return 1
    print(f"PASSED: meets the Phase 1 acceptance threshold of {threshold}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
