import pytest

from services.query_parsing import extract_spend_amount, extract_spend_category


class TestExtractSpendAmount:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("I am spending Rs. 50,000 on flights.", 50_000.0),
            ("Spending Rs. 2 lakh on hotels this month", 200_000.0),
            ("I want to pay my electricity bill of 5000 via card", 5_000.0),
            ("Spending 40k on Swiggy and Zomato", 40_000.0),
            ("INR 1500 on fuel", 1_500.0),
        ],
    )
    def test_extracts_expected_amount(self, query, expected):
        assert extract_spend_amount(query) == pytest.approx(expected)

    def test_returns_none_when_no_amount_present(self):
        assert extract_spend_amount("Which card is best for travel?") is None


class TestExtractSpendCategory:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("I am spending Rs. 50,000 on flights.", "flights"),
            ("Booking a hotel for my trip", "hotels"),
            ("Paying my electricity bill", "utility_bills"),
            ("Ordering food on Swiggy", "food_delivery_cabs"),
            ("Shopping on Amazon as a Prime member", "amazon_prime"),
            ("Amazon shopping, not a prime member", "amazon_non_prime"),
            ("Filling petrol at the pump", "fuel"),
            ("Paying my house rent", "rent"),
            # Mentions both a travel mode and a booking channel - the channel changes the
            # rate, so it must win over the more generic "flights"/"hotels" match.
            ("Booking a flight through a travel agent", "travel_agents"),
        ],
    )
    def test_extracts_expected_category(self, query, expected):
        assert extract_spend_category(query) == expected

    def test_returns_none_for_unrecognized_category(self):
        assert extract_spend_category("Booking skydiving lessons worth 3000 rupees") is None
