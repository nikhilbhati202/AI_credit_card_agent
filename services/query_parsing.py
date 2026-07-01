"""Deterministic, non-LLM query parsing for Phase 1.

Bottom-up build order (guide Section 13.1) explicitly lists "Intent Classification" as the
first *LLM-dependent* component and assigns it to Phase 2 (Section 3's Phase 2 deliverables
list it explicitly; Phase 1's deliverables do not). This module is the deterministic
placeholder that lets Phase 1's /recommend endpoint work end-to-end without an LLM: simple
regex/keyword extraction, not intent understanding. Phase 2 replaces this module's role with
a real LangGraph Intent Classification node - callers should treat this as provisional.
"""

import re

# Longer, more specific phrases are checked before shorter/generic ones within a category,
# and categories needing a positive AND a negative signal (e.g. Amazon Prime vs non-Prime)
# are ordered so the more specific category is tested first.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    # travel_agents must be checked before flights/hotels: a query like "booking a flight
    # through a travel agent" mentions both, and the booking-channel signal changes the rate.
    "travel_agents": [
        "travel agent",
        "travel agency",
        "online travel agency",
        "makemytrip",
        "goibibo",
        "via a travel",
    ],
    "flights": ["flight", "airline", "air ticket", "airfare", "plane ticket"],
    "hotels": ["hotel", "resort", "accommodation", "lodging"],
    "utility_bills": [
        "utility bill",
        "electricity bill",
        "water bill",
        "gas bill",
        "broadband bill",
        "dth recharge",
        "mobile recharge",
        "phone recharge",
    ],
    "food_delivery_cabs": ["swiggy", "zomato", "ola", "food delivery", "cab ride", "taxi ride"],
    "amazon_prime": ["amazon prime", "prime member"],
    "amazon_non_prime": ["amazon.in", "amazon"],
    "digital_categories": [
        "digital subscription",
        "ott platform",
        "digitally fulfilled",
        "digital purchase",
    ],
    "partner_brand_online": ["cleartrip", "yatra", "bookmyshow"],
    "online_shopping": [
        "online shopping",
        "shopping online",
        "e-commerce",
        "buying online",
        "online purchase",
    ],
    "offline_retail": ["offline", "in-store", "point of sale", "retail store", "at the store"],
    "fuel": ["fuel", "petrol", "diesel", "gas station", "petrol pump"],
    "rent": ["house rent", "rent payment", "paying rent", "rental payment"],
    "insurance": ["insurance premium", "insurance policy", "paying insurance"],
    "groceries": ["groceries", "grocery", "supermarket"],
}

_CURRENCY_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|l|k)?", re.I)
_SUFFIXED_AMOUNT = re.compile(r"\b([\d,]+(?:\.\d+)?)\s*(lakh|lac|k)\b", re.I)
_BARE_AMOUNT = re.compile(r"\b(\d{3,}(?:,\d{2,3})*)\b")

_SUFFIX_MULTIPLIERS = {"k": 1_000, "lakh": 100_000, "lac": 100_000, "l": 100_000}


def extract_spend_amount(query: str) -> float | None:
    """Extract a spend amount from free text. Returns None if no confident match is found -
    callers must treat that as a validation failure, never silently assume an amount.
    """
    for pattern in (_CURRENCY_AMOUNT, _SUFFIXED_AMOUNT, _BARE_AMOUNT):
        match = pattern.search(query)
        if not match:
            continue
        value = float(match.group(1).replace(",", ""))
        suffix = (
            match.group(2).lower()
            if match.lastindex and match.lastindex >= 2 and match.group(2)
            else ""
        )
        return value * _SUFFIX_MULTIPLIERS.get(suffix, 1)
    return None


_NON_PRIME_SIGNAL = re.compile(r"non[- ]prime|not a prime|without prime|no prime membership", re.I)


def extract_spend_category(query: str) -> str | None:
    """Match free text against the known spend-category vocabulary. Returns None (not
    "other") when nothing matches, so the caller can decide how to handle a genuinely
    unrecognized category rather than silently defaulting to the catch-all rate.

    Keyword matching cannot detect negation in general, but "Prime vs non-Prime" is common
    and cheap enough to special-case: a plain substring match on "prime member" would
    misclassify "not a prime member" as amazon_prime.
    """
    lowered = query.lower()
    if _NON_PRIME_SIGNAL.search(lowered) and "amazon" in lowered:
        return "amazon_non_prime"
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return None
