"""Monthly-optimization golden-set evaluation (guide Section 3 Phase 2 deliverable: expanded
golden set covering both use cases).

Deliberately bypasses Intent Classification and calls the graph's Calculation/Comparison
nodes directly with pre-parsed spend_items - both nodes are plain, LLM-free functions
(agents/nodes/calculate.py, compare.py), so this keeps the CI-gated evaluation deterministic
and free of live API calls, exactly like evaluation/calculation_eval.py does for the
single-transaction golden set (Section 13.2's bottom-up testing discipline extended to the
monthly use case).

Run directly:
    .venv/Scripts/python -m evaluation.monthly_optimization_eval
"""

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from agents.nodes.calculate import calculate
from agents.nodes.compare import compare
from database.db import SessionLocal

GOLDEN_MONTHLY_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "golden_monthly_optimization.csv"
)
VALUE_TOLERANCE = 0.01


@dataclass(frozen=True)
class ExpectedAllocation:
    category: str
    expected_card: str | None  # None means "no card should earn a reward"
    expected_value: float


@dataclass(frozen=True)
class MonthlyCase:
    id: str
    description: str
    cards_owned: list[str]
    point_valuation: float
    spend_items: list[dict]
    expected: list[ExpectedAllocation]


def _parse_spend_items(raw: str) -> list[dict]:
    items = []
    for pair in raw.split(";"):
        category, amount = pair.split(":")
        items.append({"category": category, "amount": float(amount)})
    return items


def _parse_expected(raw: str) -> list[ExpectedAllocation]:
    expected = []
    for entry in raw.split(";"):
        category, card, value = entry.split(":")
        expected.append(
            ExpectedAllocation(
                category=category,
                expected_card=None if card == "NONE" else card,
                expected_value=float(value),
            )
        )
    return expected


def load_monthly_cases(path: Path = GOLDEN_MONTHLY_PATH) -> list[MonthlyCase]:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            MonthlyCase(
                id=row["id"],
                description=row["description"],
                cards_owned=row["cards_owned"].split(";"),
                point_valuation=float(row["point_valuation"]),
                spend_items=_parse_spend_items(row["spend_items"]),
                expected=_parse_expected(row["expected_allocation"]),
            )
            for row in reader
        ]


def _check_case(case: MonthlyCase) -> list[str]:
    """Returns a list of failure messages (empty means the case passed)."""
    db = SessionLocal()
    try:
        config = {"configurable": {"db": db}}
        state = {
            "cards_owned": case.cards_owned,
            "spend_items": case.spend_items,
            "point_valuation": case.point_valuation,
            "retrieved_chunks": [],
        }
        calc_result = calculate(state, config)
        compare_result = compare({**state, **calc_result})
        ranked = compare_result["ranked_comparison"]
    finally:
        db.close()

    failures = []
    for expected in case.expected:
        results = ranked.get(expected.category, [])
        best = results[0] if results else None

        if expected.expected_card is None:
            if best is not None and best["reward_value"] > 0:
                got = f"{best['card_name']}={best['reward_value']}"
                failures.append(f"{expected.category}: expected no reward, got {got}")
            continue

        if best is None:
            failures.append(
                f"{expected.category}: expected {expected.expected_card}, got no result"
            )
            continue
        if best["card_name"] != expected.expected_card:
            failures.append(
                f"{expected.category}: expected card {expected.expected_card}, "
                f"got {best['card_name']}"
            )
        elif abs(best["reward_value"] - expected.expected_value) > VALUE_TOLERANCE:
            failures.append(
                f"{expected.category}: expected value {expected.expected_value}, "
                f"got {best['reward_value']}"
            )
    return failures


def run() -> dict[str, list[str]]:
    return {case.id: _check_case(case) for case in load_monthly_cases()}


def main() -> int:
    results = run()
    total_checks = 0
    failed_checks = 0
    for case_id, failures in results.items():
        case = next(c for c in load_monthly_cases() if c.id == case_id)
        total_checks += len(case.expected)
        if failures:
            failed_checks += len(failures)
            print(f"[FAIL] {case_id}: {case.description}")
            for f in failures:
                print(f"    - {f}")
        else:
            print(f"[PASS] {case_id}: {case.description} ({len(case.expected)} categories)")

    accuracy = (total_checks - failed_checks) / total_checks * 100 if total_checks else 0.0
    passed_checks = total_checks - failed_checks
    print(f"\nMonthly-optimization accuracy: {accuracy:.1f}% ({passed_checks}/{total_checks})")

    if failed_checks:
        print(
            "FAILED: at least one category allocation did not match the hand-computed expectation."
        )
        return 1
    print("PASSED: 100% monthly-optimization calculation accuracy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
