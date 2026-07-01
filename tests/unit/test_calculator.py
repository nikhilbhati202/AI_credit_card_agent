"""Exhaustive unit tests for tools/calculator.py - the 100%-or-fail bar (Section 18.4).

Every expected value below is hand-computed, not derived from running the code, per
Section 18.2's golden-dataset discipline applied to the calculator itself.
"""

import pytest

from tools.calculator import CapBasis, RewardUnit, calculate_reward


class TestBasicCalculation:
    def test_cashback_no_cap(self):
        result = calculate_reward(spend_amount=1000, reward_rate=5, reward_unit=RewardUnit.CASHBACK)
        assert result.base_reward_units == pytest.approx(50.0)
        assert result.reward_value == pytest.approx(50.0)
        assert result.effective_return_pct == pytest.approx(5.0)
        assert result.cap_applied is False

    def test_miles_no_cap_matches_architecture_doc_example(self):
        # Architecture doc Section 13: Rs.50,000 flights on Axis Atlas -> 2500 miles -> Rs.2500.
        result = calculate_reward(
            spend_amount=50000,
            reward_rate=5,
            reward_unit=RewardUnit.MILES,
            point_valuation=1.0,
        )
        assert result.base_reward_units == pytest.approx(2500.0)
        assert result.reward_value == pytest.approx(2500.0)
        assert result.effective_return_pct == pytest.approx(5.0)

    def test_points_value_scales_with_point_valuation(self):
        result = calculate_reward(
            spend_amount=1000, reward_rate=10, reward_unit=RewardUnit.POINTS, point_valuation=0.25
        )
        assert result.base_reward_units == pytest.approx(100.0)
        assert result.reward_value == pytest.approx(25.0)


class TestSpendBasisCap:
    """Axis Atlas-shaped: 5x up to Rs.2L spend/month, 2x beyond."""

    def test_spend_above_cap_splits_at_two_rates(self):
        result = calculate_reward(
            spend_amount=250_000,
            reward_rate=5,
            reward_unit=RewardUnit.MILES,
            cap_basis=CapBasis.SPEND,
            cap_value=200_000,
            excess_reward_rate=2,
        )
        # 200,000/100*5 = 10,000 ; 50,000/100*2 = 1,000 -> 11,000 miles
        assert result.base_reward_units == pytest.approx(11_000.0)
        assert result.reward_value == pytest.approx(11_000.0)
        assert result.cap_applied is True

    def test_spend_exactly_at_cap_boundary_not_marked_applied(self):
        result = calculate_reward(
            spend_amount=200_000,
            reward_rate=5,
            reward_unit=RewardUnit.MILES,
            cap_basis=CapBasis.SPEND,
            cap_value=200_000,
            excess_reward_rate=2,
        )
        assert result.base_reward_units == pytest.approx(10_000.0)
        assert result.cap_applied is False

    def test_spend_below_cap_uses_only_base_rate(self):
        result = calculate_reward(
            spend_amount=50_000,
            reward_rate=5,
            reward_unit=RewardUnit.MILES,
            cap_basis=CapBasis.SPEND,
            cap_value=200_000,
            excess_reward_rate=2,
        )
        assert result.base_reward_units == pytest.approx(2_500.0)
        assert result.cap_applied is False

    def test_no_excess_rate_means_zero_reward_beyond_cap(self):
        result = calculate_reward(
            spend_amount=300_000,
            reward_rate=5,
            reward_unit=RewardUnit.MILES,
            cap_basis=CapBasis.SPEND,
            cap_value=200_000,
        )
        assert result.base_reward_units == pytest.approx(10_000.0)
        assert result.cap_applied is True


class TestRewardUnitsBasisCap:
    """SBI SimplyCLICK-shaped: 5x online capped at 10,000 points/month, then 1x."""

    def test_spend_above_units_cap_splits_correctly(self):
        result = calculate_reward(
            spend_amount=250_000,
            reward_rate=5,
            reward_unit=RewardUnit.POINTS,
            cap_basis=CapBasis.REWARD_UNITS,
            cap_value=10_000,
            excess_reward_rate=1,
        )
        # Threshold spend = 10,000 / 5 * 100 = 200,000
        # 200,000/100*5 = 10,000 ; 50,000/100*1 = 500 -> 10,500 points
        assert result.base_reward_units == pytest.approx(10_500.0)
        assert result.cap_applied is True

    def test_spend_exactly_at_units_cap_threshold_not_marked_applied(self):
        result = calculate_reward(
            spend_amount=200_000,
            reward_rate=5,
            reward_unit=RewardUnit.POINTS,
            cap_basis=CapBasis.REWARD_UNITS,
            cap_value=10_000,
            excess_reward_rate=1,
        )
        assert result.base_reward_units == pytest.approx(10_000.0)
        assert result.cap_applied is False

    def test_cashback_reward_units_cap_axis_ace_shaped(self):
        # Axis ACE-shaped: 5% capped at Rs.500 cashback/month, no reward beyond cap.
        result = calculate_reward(
            spend_amount=40_000,
            reward_rate=5,
            reward_unit=RewardUnit.CASHBACK,
            cap_basis=CapBasis.REWARD_UNITS,
            cap_value=500,
        )
        # Threshold spend = 500 / 5 * 100 = 10,000 ; beyond that, excess_reward_rate=0
        assert result.base_reward_units == pytest.approx(500.0)
        assert result.reward_value == pytest.approx(500.0)
        assert result.cap_applied is True

    def test_reward_rate_zero_with_units_cap_raises(self):
        with pytest.raises(ValueError, match="reward_rate must be positive"):
            calculate_reward(
                spend_amount=1000,
                reward_rate=0,
                reward_unit=RewardUnit.POINTS,
                cap_basis=CapBasis.REWARD_UNITS,
                cap_value=500,
            )


class TestMilestones:
    def test_milestone_triggered_when_spend_meets_lowest_threshold(self):
        result = calculate_reward(
            spend_amount=300_000,
            reward_rate=2,
            reward_unit=RewardUnit.MILES,
            milestone_thresholds=[300_000, 750_000, 1_500_000],
        )
        assert result.milestone_triggered is True

    def test_milestone_not_triggered_below_lowest_threshold(self):
        result = calculate_reward(
            spend_amount=100_000,
            reward_rate=2,
            reward_unit=RewardUnit.MILES,
            milestone_thresholds=[300_000, 750_000],
        )
        assert result.milestone_triggered is False

    def test_no_thresholds_means_never_triggered(self):
        result = calculate_reward(
            spend_amount=1_000_000, reward_rate=2, reward_unit=RewardUnit.MILES
        )
        assert result.milestone_triggered is False


class TestValidationNeverSilentlyDefaults:
    def test_zero_spend_rejected(self):
        with pytest.raises(ValueError, match="spend_amount must be positive"):
            calculate_reward(spend_amount=0, reward_rate=5, reward_unit=RewardUnit.CASHBACK)

    def test_negative_spend_rejected(self):
        with pytest.raises(ValueError, match="spend_amount must be positive"):
            calculate_reward(spend_amount=-500, reward_rate=5, reward_unit=RewardUnit.CASHBACK)

    def test_negative_reward_rate_rejected(self):
        with pytest.raises(ValueError, match="reward_rate cannot be negative"):
            calculate_reward(spend_amount=1000, reward_rate=-1, reward_unit=RewardUnit.CASHBACK)

    def test_negative_excess_reward_rate_rejected(self):
        with pytest.raises(ValueError, match="excess_reward_rate cannot be negative"):
            calculate_reward(
                spend_amount=1000,
                reward_rate=5,
                reward_unit=RewardUnit.CASHBACK,
                cap_basis=CapBasis.SPEND,
                cap_value=500,
                excess_reward_rate=-1,
            )

    def test_non_positive_point_valuation_rejected(self):
        with pytest.raises(ValueError, match="point_valuation must be positive"):
            calculate_reward(
                spend_amount=1000, reward_rate=5, reward_unit=RewardUnit.POINTS, point_valuation=0
            )

    def test_cap_value_without_cap_basis_rejected(self):
        with pytest.raises(ValueError, match="cap_basis and cap_value must be provided together"):
            calculate_reward(
                spend_amount=1000, reward_rate=5, reward_unit=RewardUnit.CASHBACK, cap_value=500
            )

    def test_cap_basis_without_cap_value_rejected(self):
        with pytest.raises(ValueError, match="cap_basis and cap_value must be provided together"):
            calculate_reward(
                spend_amount=1000,
                reward_rate=5,
                reward_unit=RewardUnit.CASHBACK,
                cap_basis=CapBasis.SPEND,
            )

    def test_non_positive_cap_value_rejected(self):
        with pytest.raises(ValueError, match="cap_value must be positive"):
            calculate_reward(
                spend_amount=1000,
                reward_rate=5,
                reward_unit=RewardUnit.CASHBACK,
                cap_basis=CapBasis.SPEND,
                cap_value=0,
            )

    def test_missing_reward_rate_is_a_type_error_not_a_silent_default(self):
        with pytest.raises(TypeError):
            calculate_reward(spend_amount=1000, reward_unit=RewardUnit.CASHBACK)  # type: ignore[call-arg]
