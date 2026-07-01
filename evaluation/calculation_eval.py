"""Calculation accuracy against the golden set (guide Section 18.3/20).

100%-or-fail bar (Section 18.4): calculation accuracy must never drop below 100% - there is
no acceptable tolerance for arithmetic drift in this domain. Run directly:
    .venv/Scripts/python -m evaluation.calculation_eval
"""

import sys
from dataclasses import dataclass

from database.db import SessionLocal
from evaluation.golden_dataset import GoldenCase, load_golden_cases
from services.recommendation_service import recommend

VALUE_TOLERANCE = 0.01  # rupees; float rounding only, not a real tolerance for drift


@dataclass(frozen=True)
class CaseResult:
    case: GoldenCase
    passed: bool
    reason: str


def _check_case(case: GoldenCase) -> CaseResult:
    db = SessionLocal()
    try:
        result = recommend(
            db=db,
            query=case.query,
            cards_owned=case.cards_owned,
            point_valuation=case.point_valuation,
        )
    finally:
        db.close()

    if case.expected_outcome == "insufficient_information":
        if result.insufficient_information:
            return CaseResult(case, True, "ok")
        return CaseResult(case, False, f"expected insufficient_information, got {result}")

    if case.expected_outcome == "none_reward":
        if not result.insufficient_information and result.recommended_card is None:
            return CaseResult(case, True, "ok")
        return CaseResult(case, False, f"expected none_reward, got {result}")

    # expected_outcome == "recommended"
    if result.recommended_card != case.expected_recommended_card:
        return CaseResult(
            case,
            False,
            f"expected card {case.expected_recommended_card!r}, got {result.recommended_card!r}",
        )
    assert case.expected_estimated_reward_value is not None
    if result.estimated_reward_value is None or (
        abs(result.estimated_reward_value - case.expected_estimated_reward_value) > VALUE_TOLERANCE
    ):
        return CaseResult(
            case,
            False,
            f"expected value {case.expected_estimated_reward_value}, "
            f"got {result.estimated_reward_value}",
        )
    assert case.expected_effective_return_pct is not None
    if result.effective_return_pct is None or (
        abs(result.effective_return_pct - case.expected_effective_return_pct) > 0.05
    ):
        return CaseResult(
            case,
            False,
            f"expected pct {case.expected_effective_return_pct}, got {result.effective_return_pct}",
        )
    return CaseResult(case, True, "ok")


def run() -> list[CaseResult]:
    return [_check_case(case) for case in load_golden_cases()]


def main() -> int:
    results = run()
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] #{r.case.id}: {r.case.query!r} -> {r.reason}")

    accuracy = len(passed) / len(results) * 100 if results else 0.0
    print(f"\nCalculation accuracy: {accuracy:.1f}% ({len(passed)}/{len(results)})")

    if failed:
        print(f"FAILED: {len(failed)} case(s) did not match hand-computed expected values.")
        return 1
    print("PASSED: 100% calculation accuracy (Section 18.4 gate).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
