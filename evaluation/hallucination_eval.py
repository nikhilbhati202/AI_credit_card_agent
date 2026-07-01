"""Hallucination-rate check, scoped to what Phase 1 actually generates (guide Section 20).

Phase 1's /recommend response is entirely templated from calculator output and retrieved
citations - no LLM composes free text yet (that's Phase 2/3's Final Answer node, Section
14.1). So "hallucination" here means something narrower but still real: every numeric claim
in a response must independently reproduce from a fresh DB lookup + calculator call, never
drift from its source. Full free-text hallucination-rate evaluation (an LLM's prose against
retrieved evidence) is a Phase 2+ concern once that generation step exists.

Run directly:
    .venv/Scripts/python -m evaluation.hallucination_eval
"""

import sys
from dataclasses import dataclass

from sqlalchemy import select

from database.db import SessionLocal
from database.models import RewardRule
from database.models import RewardRuleStatus as DbStatus
from evaluation.golden_dataset import GoldenCase, load_golden_cases
from services.recommendation_service import recommend


@dataclass(frozen=True)
class GroundingCheck:
    case: GoldenCase
    grounded: bool
    reason: str


def _check_case(case: GoldenCase) -> GroundingCheck:
    if case.expected_outcome != "recommended":
        return GroundingCheck(case, True, "not applicable (no numeric claim expected)")

    db = SessionLocal()
    try:
        result = recommend(
            db=db,
            query=case.query,
            cards_owned=case.cards_owned,
            point_valuation=case.point_valuation,
        )
        if result.recommended_card is None or result.calculation is None:
            return GroundingCheck(case, False, "expected a recommendation but got none")

        rule = db.execute(
            select(RewardRule).where(
                RewardRule.card_name == result.recommended_card,
                RewardRule.spend_category == result.spend_category,
                RewardRule.status == DbStatus.ACTIVE,
            )
        ).scalar_one_or_none()
        if rule is None:
            return GroundingCheck(case, False, "recommended card has no matching DB rule")

        if result.calculation["reward_rate"] != rule.reward_rate:
            return GroundingCheck(
                case,
                False,
                f"reported reward_rate {result.calculation['reward_rate']} "
                f"!= DB rule {rule.reward_rate}",
            )
        if not result.rules_used and not rule.exclusion_flag:
            return GroundingCheck(
                case, False, "no citation attached to a non-excluded recommendation"
            )
        return GroundingCheck(case, True, "ok")
    finally:
        db.close()


def run() -> list[GroundingCheck]:
    return [_check_case(case) for case in load_golden_cases()]


def main() -> int:
    results = run()
    for r in results:
        print(f"[{'OK' if r.grounded else 'UNGROUNDED'}] #{r.case.id}: {r.reason}")

    ungrounded = [r for r in results if not r.grounded]
    rate = len(ungrounded) / len(results) * 100 if results else 0.0
    print(f"\nUngrounded-claim rate: {rate:.1f}% ({len(ungrounded)}/{len(results)})")

    if ungrounded:
        print("FAILED: at least one numeric claim did not trace back to its DB source.")
        return 1
    print("PASSED: 0% ungrounded numeric claims (Section 18.4 gate).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
