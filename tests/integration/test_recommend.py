"""Integration tests for POST /api/v1/recommend against the seeded mock card (Section 6.6:
tests use mock data, never real card data that can change).
"""

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_recommend_returns_cited_answer_for_known_category() -> None:
    response = client.post(
        "/api/v1/recommend",
        json={"query": "Spending Rs. 5000 on groceries", "cards_owned": ["Test Card Alpha"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommended_card"] == "Test Card Alpha"
    assert body["estimated_reward_value"] == 500.0
    assert body["insufficient_information"] is False
    # Test Card Alpha is synthetic mock data (Section 6.6) with no ingested document chunks,
    # so it has no source_chunk_id to cite - unlike the 5 real seeded cards.
    assert body["rules_used"] == []


def test_recommend_returns_insufficient_information_for_unknown_category() -> None:
    response = client.post(
        "/api/v1/recommend",
        json={
            "query": "Spending Rs. 5000 on skydiving lessons",
            "cards_owned": ["Test Card Alpha"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["insufficient_information"] is True
    assert body["recommended_card"] is None


def test_recommend_rejects_missing_spend_amount() -> None:
    response = client.post(
        "/api/v1/recommend",
        json={
            "query": "Which card should I use for groceries?",
            "cards_owned": ["Test Card Alpha"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_recommend_rejects_empty_cards_owned() -> None:
    response = client.post(
        "/api/v1/recommend",
        json={"query": "Spending Rs. 5000 on groceries", "cards_owned": []},
    )

    assert response.status_code == 422


def test_recommend_rejects_non_positive_point_valuation() -> None:
    response = client.post(
        "/api/v1/recommend",
        json={
            "query": "Spending Rs. 5000 on groceries",
            "cards_owned": ["Test Card Alpha"],
            "point_valuation": 0,
        },
    )

    assert response.status_code == 422
