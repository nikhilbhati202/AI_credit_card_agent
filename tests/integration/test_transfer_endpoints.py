"""Integration tests for POST /api/v1/transfer/evaluate and /api/v1/transfer/confirm
(guide Section 3 Phase 3 acceptance criterion, exercised over real HTTP this time rather
than by driving the compiled graph directly as tests/agent/test_transfer_flow.py does).
"""

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def _mock_transfer_intent(mock_intent_classification, partner_name: str, miles: float = 10_000):
    mock_intent_classification(
        intent="transfer_evaluation",
        confidence=0.95,
        spend_items=[],
        transfer_partner_name=partner_name,
        transfer_miles_amount=miles,
    )


class TestTransferEvaluate:
    def test_evaluate_returns_pending_approval_and_never_finalizes(
        self, mock_intent_classification
    ) -> None:
        _mock_transfer_intent(mock_intent_classification, "Singapore Airlines KrisFlyer")

        response = client.post(
            "/api/v1/transfer/evaluate",
            json={
                "query": "Should I transfer 10000 miles to Singapore Airlines KrisFlyer?",
                "cards_owned": ["Axis Atlas"],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending_approval"
        assert body["proposal"]["partner_name"] == "Singapore Airlines KrisFlyer"
        assert body["session_id"]

    def test_evaluate_asks_a_clarifying_question_for_an_unknown_partner(
        self, mock_intent_classification, mock_clarify_llm
    ) -> None:
        mock_intent_classification(
            intent="transfer_evaluation",
            confidence=0.9,
            spend_items=[],
            transfer_partner_name="Made-Up Frequent Flyer Program",
            transfer_miles_amount=10_000,
        )
        mock_clarify_llm("That partner isn't linked to any card you own - which one did you mean?")

        response = client.post(
            "/api/v1/transfer/evaluate",
            json={
                "query": "Transfer 10000 miles to a made-up frequent flyer program",
                "cards_owned": ["Axis Atlas"],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "clarification_needed"
        assert body["follow_up_question"]

    def test_evaluate_returns_409_when_session_already_has_a_pending_approval(
        self, mock_intent_classification
    ) -> None:
        _mock_transfer_intent(mock_intent_classification, "Singapore Airlines KrisFlyer")
        first = client.post(
            "/api/v1/transfer/evaluate",
            json={
                "query": "Transfer 10000 miles to Singapore Airlines KrisFlyer",
                "cards_owned": ["Axis Atlas"],
            },
        )
        session_id = first.json()["session_id"]

        second = client.post(
            "/api/v1/transfer/evaluate",
            json={
                "query": "Transfer 5000 more miles to Singapore Airlines KrisFlyer",
                "cards_owned": ["Axis Atlas"],
                "session_id": session_id,
            },
        )

        assert second.status_code == 409
        assert second.json()["error"]["code"] == "approval_pending"

    def test_evaluate_rejects_empty_cards_owned(self) -> None:
        response = client.post(
            "/api/v1/transfer/evaluate",
            json={"query": "Transfer 10000 miles to KrisFlyer", "cards_owned": []},
        )

        assert response.status_code == 422

    def test_evaluate_returns_503_when_llm_unavailable(self, monkeypatch) -> None:
        from agents.llm import LLMUnavailableError

        def _raise(*args, **kwargs):
            raise LLMUnavailableError("simulated API outage")

        monkeypatch.setattr("backend.api.routes_transfer.run_agent", _raise)

        response = client.post(
            "/api/v1/transfer/evaluate",
            json={"query": "Transfer 10000 miles to KrisFlyer", "cards_owned": ["Axis Atlas"]},
        )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "llm_unavailable"


class TestTransferConfirm:
    def test_confirm_approved_finalizes_the_transfer(
        self, mock_intent_classification, mock_final_answer_llm
    ) -> None:
        _mock_transfer_intent(mock_intent_classification, "Singapore Airlines KrisFlyer")
        mock_final_answer_llm("Transfer approved and processed.")

        evaluate_response = client.post(
            "/api/v1/transfer/evaluate",
            json={
                "query": "Transfer 10000 miles to Singapore Airlines KrisFlyer",
                "cards_owned": ["Axis Atlas"],
            },
        )
        session_id = evaluate_response.json()["session_id"]

        confirm_response = client.post(
            "/api/v1/transfer/confirm", json={"session_id": session_id, "approved": True}
        )

        assert confirm_response.status_code == 200
        body = confirm_response.json()
        assert body["approval_status"] == "approved"
        assert body["transfer_proposal"]["partner_name"] == "Singapore Airlines KrisFlyer"
        assert "confirmed" in body["message"].lower()

    def test_confirm_rejected_cancels_without_finalizing(
        self, mock_intent_classification, mock_final_answer_llm
    ) -> None:
        _mock_transfer_intent(mock_intent_classification, "Singapore Airlines KrisFlyer")
        mock_final_answer_llm("Transfer cancelled as requested.")

        evaluate_response = client.post(
            "/api/v1/transfer/evaluate",
            json={
                "query": "Transfer 10000 miles to Singapore Airlines KrisFlyer",
                "cards_owned": ["Axis Atlas"],
            },
        )
        session_id = evaluate_response.json()["session_id"]

        confirm_response = client.post(
            "/api/v1/transfer/confirm", json={"session_id": session_id, "approved": False}
        )

        assert confirm_response.status_code == 200
        body = confirm_response.json()
        assert body["approval_status"] == "rejected"
        assert "cancelled" in body["message"].lower()

    def test_confirm_returns_404_when_no_pending_approval_for_session(self) -> None:
        response = client.post(
            "/api/v1/transfer/confirm",
            json={"session_id": "nonexistent-session-id", "approved": True},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "no_pending_approval"
