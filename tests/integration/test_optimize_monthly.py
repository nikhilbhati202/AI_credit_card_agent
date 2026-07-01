from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_optimize_monthly_allocates_across_categories(
    mock_intent_classification, mock_final_answer_llm
):
    mock_intent_classification(
        intent="monthly_optimization",
        confidence=0.92,
        spend_items=[
            {"category": "flights", "amount": 50000},
            {"category": "utility_bills", "amount": 4000},
        ],
    )
    mock_final_answer_llm("Here is your allocation plan.")

    response = client.post(
        "/api/v1/optimize/monthly",
        json={
            "query": "Monthly: 50000 flights, 4000 utility bills",
            "cards_owned": ["Axis Atlas", "Axis ACE", "SBI Cashback"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["allocation"]) == 2
    assert body["total_estimated_reward_value"] > 0
    assert body["session_id"]


def test_optimize_monthly_rejects_fewer_than_three_cards():
    response = client.post(
        "/api/v1/optimize/monthly",
        json={"query": "Monthly spend breakdown", "cards_owned": ["Axis Atlas"]},
    )

    assert response.status_code == 422
