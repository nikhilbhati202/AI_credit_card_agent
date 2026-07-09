"""Tests for a real production gap found via user feedback: the structured result never
exposed (a) how many points/miles/Rs. were actually earned, independent of point_valuation,
or (b) what a capped reward would have been without the cap - forcing the LLM to either guess
these via arithmetic (Section 15.1 forbids this) or omit the cap context entirely, and
directly causing a real observed narrative error ("25,000 miles" instead of the correct 2,500,
when point_valuation != 1 - the model conflated units-earned with Rupee value because nothing
in the structured data separated the two).

services/recommendation_service.py's evaluate_card() now always returns base_reward_units
(the earned-units count, independent of point_valuation) and, only when a cap changed the
outcome, uncapped_reward_value (what the reward would have been with no cap).
"""

from database.db import SessionLocal
from services.recommendation_service import evaluate_card


class TestBaseRewardUnitsIndependentOfPointValuation:
    def test_units_earned_do_not_scale_with_point_valuation(self):
        db = SessionLocal()
        try:
            at_valuation_1 = evaluate_card(
                db, "Axis Atlas", "flights", 50000.0, point_valuation=1.0, retrieved=[]
            )
            at_valuation_100 = evaluate_card(
                db, "Axis Atlas", "flights", 50000.0, point_valuation=100.0, retrieved=[]
            )
        finally:
            db.close()

        assert at_valuation_1 is not None
        assert at_valuation_100 is not None
        # The actual miles earned never changes - only the Rupee value assigned to them does.
        assert at_valuation_1.base_reward_units == 2500.0
        assert at_valuation_100.base_reward_units == 2500.0
        assert at_valuation_1.reward_value == 2500.0
        assert at_valuation_100.reward_value == 250000.0


class TestUncappedRewardValueTransparency:
    def test_uncapped_reward_value_is_none_when_no_cap_applies(self):
        db = SessionLocal()
        try:
            evaluation = evaluate_card(
                db, "Axis Atlas", "flights", 50000.0, point_valuation=1.0, retrieved=[]
            )
        finally:
            db.close()

        assert evaluation is not None
        assert evaluation.cap_applied is False
        assert evaluation.uncapped_reward_value is None

    def test_uncapped_reward_value_is_populated_when_a_cap_applies(self):
        """SBI Cashback: 5% online, capped at Rs.2,000 cashback/month (REWARD_UNITS basis) -
        reached at Rs.40,000 spend. Spending Rs.60,000 hits the cap (golden row #12).
        """
        db = SessionLocal()
        try:
            evaluation = evaluate_card(
                db, "SBI Cashback", "online_shopping", 60000.0, point_valuation=1.0, retrieved=[]
            )
        finally:
            db.close()

        assert evaluation is not None
        assert evaluation.cap_applied is True
        assert evaluation.reward_value == 2000.0
        # Uncapped: the full Rs.60,000 at the 5% rate, ignoring the cap entirely.
        assert evaluation.uncapped_reward_value == 3000.0
        assert evaluation.uncapped_reward_value > evaluation.reward_value
