"""Integration tests for POST /api/v1/recommend.

Uses real seeded cards (Axis Atlas et al.) rather than the "Test Card Alpha" mock (Section
6.6): the graph's Rule Validation node requires retrieved evidence (Section 14.1), and the
mock card intentionally has no ingested document chunks (it exists for isolated
calculator/service-layer tests, not for exercising the full RAG-gated pipeline).

The graph's two LLM calls are mocked (tests/conftest.py) so this suite runs without a live
LLM endpoint - it still exercises the real HTTP layer, real DB queries, and real
calculator/retriever logic end-to-end, only the LLM's two calls are stubbed.
"""

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_recommend_returns_cited_answer_for_known_category(
    mock_intent_classification, mock_final_answer_llm
) -> None:
    mock_intent_classification(
        intent="single_transaction",
        confidence=0.95,
        spend_items=[{"category": "flights", "amount": 50000}],
    )
    mock_final_answer_llm("Axis Atlas is the best choice for this flight spend.")

    response = client.post(
        "/api/v1/recommend",
        json={"query": "Spending Rs. 50,000 on flights", "cards_owned": ["Axis Atlas", "Axis ACE"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommended_card"] == "Axis Atlas"
    assert body["estimated_reward_value"] == 2500.0
    assert body["insufficient_information"] is False
    assert body["session_id"]
    assert len(body["rules_used"]) == 1
    assert body["explanation"] == "Axis Atlas is the best choice for this flight spend."


def test_recommend_returns_insufficient_information_for_a_category_no_owned_card_covers(
    mock_intent_classification, mock_final_answer_llm
) -> None:
    mock_intent_classification(
        intent="single_transaction",
        confidence=0.9,
        spend_items=[{"category": "insurance", "amount": 5000}],
    )
    mock_final_answer_llm()

    response = client.post(
        "/api/v1/recommend",
        json={"query": "Spending Rs. 5000 on an insurance premium", "cards_owned": ["Axis Atlas"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["insufficient_information"] is True
    assert body["recommended_card"] is None


def test_recommend_asks_a_clarifying_question_for_an_ambiguous_query(
    mock_intent_classification, mock_clarify_llm
) -> None:
    mock_intent_classification(intent="unclear", confidence=0.2, ambiguity_reason="no amount given")
    mock_clarify_llm("How much are you planning to spend, and on what?")

    response = client.post(
        "/api/v1/recommend",
        json={"query": "Which card should I use?", "cards_owned": ["Axis Atlas"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["follow_up_question"] == "How much are you planning to spend, and on what?"
    assert body["recommended_card"] is None
    assert body["session_id"]


def test_recommend_surfaces_a_pending_transfer_approval_instead_of_an_empty_response(
    mock_intent_classification,
) -> None:
    """A transfer-shaped query can reach /recommend directly (a single chat UI drives every
    intent through this endpoint) - it must pause and report the proposal, not silently
    return an empty-looking body (the bug this test guards against).
    """
    mock_intent_classification(
        intent="transfer_evaluation",
        confidence=0.95,
        spend_items=[],
        transfer_partner_name="Singapore Airlines KrisFlyer",
        transfer_miles_amount=10_000,
    )

    response = client.post(
        "/api/v1/recommend",
        json={
            "query": "Should I transfer 10000 miles to Singapore Airlines KrisFlyer?",
            "cards_owned": ["Axis Atlas"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["approval_pending"] is True
    assert body["transfer_proposal"]["partner_name"] == "Singapore Airlines KrisFlyer"
    assert body["recommended_card"] is None


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
            "cards_owned": ["Axis Atlas"],
            "point_valuation": 0,
        },
    )

    assert response.status_code == 422


def test_recommend_returns_503_when_llm_unavailable(monkeypatch) -> None:
    from agents.llm import LLMUnavailableError

    def _raise(*args, **kwargs):
        raise LLMUnavailableError("simulated API outage")

    monkeypatch.setattr("backend.api.routes_recommend.run_agent", _raise)

    response = client.post(
        "/api/v1/recommend",
        json={"query": "Spending Rs. 5000 on groceries", "cards_owned": ["Axis Atlas"]},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_unavailable"
