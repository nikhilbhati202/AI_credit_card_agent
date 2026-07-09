"""Exhaustive unit tests for tools/transfer_calculator.py, same rigor bar as the reward
calculator (Section 18.2/18.4): every expected value is hand-computed.
"""

import pytest

from tools.transfer_calculator import calculate_transfer_value


class TestBasicComparison:
    def test_equal_value_when_ratio_and_valuations_cancel_out(self):
        # KrisFlyer-shaped: 1:2 ratio, partner point worth half as much as the issuer's own.
        result = calculate_transfer_value(
            miles_amount=10_000,
            transfer_ratio_from=1,
            transfer_ratio_to=2,
            partner_point_valuation=0.5,
            direct_point_valuation=1.0,
        )
        assert result.partner_units_received == pytest.approx(20_000)
        assert result.transfer_value == pytest.approx(10_000)
        assert result.direct_redemption_value == pytest.approx(10_000)
        assert result.better_option == "equal"

    def test_transfer_wins_when_partner_valuation_is_high_enough(self):
        result = calculate_transfer_value(
            miles_amount=10_000,
            transfer_ratio_from=1,
            transfer_ratio_to=2,
            partner_point_valuation=0.8,
            direct_point_valuation=1.0,
        )
        assert result.transfer_value == pytest.approx(16_000)
        assert result.value_difference == pytest.approx(6_000)
        assert result.better_option == "transfer"

    def test_redeem_directly_wins_with_an_inverted_ratio(self):
        # British Airways-shaped: 2 EDGE Miles = 1 Avios (inverted ratio).
        result = calculate_transfer_value(
            miles_amount=10_000,
            transfer_ratio_from=2,
            transfer_ratio_to=1,
            partner_point_valuation=1.5,
            direct_point_valuation=1.0,
        )
        assert result.partner_units_received == pytest.approx(5_000)
        assert result.transfer_value == pytest.approx(7_500)
        assert result.direct_redemption_value == pytest.approx(10_000)
        assert result.value_difference == pytest.approx(-2_500)
        assert result.better_option == "redeem_directly"


class TestValidationNeverSilentlyDefaults:
    def test_non_positive_miles_amount_rejected(self):
        with pytest.raises(ValueError, match="miles_amount must be positive"):
            calculate_transfer_value(
                miles_amount=0,
                transfer_ratio_from=1,
                transfer_ratio_to=2,
                partner_point_valuation=1.0,
            )

    def test_non_positive_ratio_from_rejected(self):
        with pytest.raises(ValueError, match="transfer_ratio_from and transfer_ratio_to"):
            calculate_transfer_value(
                miles_amount=1000,
                transfer_ratio_from=0,
                transfer_ratio_to=2,
                partner_point_valuation=1.0,
            )

    def test_non_positive_ratio_to_rejected(self):
        with pytest.raises(ValueError, match="transfer_ratio_from and transfer_ratio_to"):
            calculate_transfer_value(
                miles_amount=1000,
                transfer_ratio_from=1,
                transfer_ratio_to=0,
                partner_point_valuation=1.0,
            )

    def test_non_positive_partner_valuation_rejected(self):
        with pytest.raises(ValueError, match="partner_point_valuation must be positive"):
            calculate_transfer_value(
                miles_amount=1000,
                transfer_ratio_from=1,
                transfer_ratio_to=2,
                partner_point_valuation=0,
            )

    def test_non_positive_direct_valuation_rejected(self):
        with pytest.raises(ValueError, match="direct_point_valuation must be positive"):
            calculate_transfer_value(
                miles_amount=1000,
                transfer_ratio_from=1,
                transfer_ratio_to=2,
                partner_point_valuation=1.0,
                direct_point_valuation=0,
            )

    def test_missing_required_argument_is_a_type_error(self):
        with pytest.raises(TypeError):
            calculate_transfer_value(miles_amount=1000, transfer_ratio_from=1, transfer_ratio_to=2)  # type: ignore[call-arg]
