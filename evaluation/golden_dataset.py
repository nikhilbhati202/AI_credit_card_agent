"""Loader for the hand-curated golden dataset (guide Section 18.2; data/golden_answers.csv).

Kept separate from both seed data and mock data (Section 6.6) - this is a first-class,
version-controlled project artifact, not a scratch file.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

GOLDEN_ANSWERS_PATH = Path(__file__).resolve().parent.parent / "data" / "golden_answers.csv"


@dataclass(frozen=True)
class GoldenCase:
    id: int
    query: str
    cards_owned: list[str]
    point_valuation: float
    expected_category: str
    expected_outcome: str  # "recommended" | "none_reward" | "insufficient_information"
    expected_recommended_card: str | None
    expected_estimated_reward_value: float | None
    expected_effective_return_pct: float | None
    notes: str


def load_golden_cases(path: Path = GOLDEN_ANSWERS_PATH) -> list[GoldenCase]:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            GoldenCase(
                id=int(row["id"]),
                query=row["query"],
                cards_owned=row["cards_owned"].split(";"),
                point_valuation=float(row["point_valuation"]),
                expected_category=row["expected_category"],
                expected_outcome=row["expected_outcome"],
                expected_recommended_card=row["expected_recommended_card"] or None,
                expected_estimated_reward_value=(
                    float(row["expected_estimated_reward_value"])
                    if row["expected_estimated_reward_value"]
                    else None
                ),
                expected_effective_return_pct=(
                    float(row["expected_effective_return_pct"])
                    if row["expected_effective_return_pct"]
                    else None
                ),
                notes=row["notes"],
            )
            for row in reader
        ]
