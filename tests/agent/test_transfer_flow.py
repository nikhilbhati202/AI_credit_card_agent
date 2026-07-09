"""Agent-level test for the transfer-evaluation flow (guide Section 3 Phase 3 acceptance
criterion: "No transfer calculation is ever finalized without an explicit approval step
observed in a trace").

Drives the compiled graph directly with LangGraph's real interrupt()/Command(resume=...)
primitive (Section 10.11) - the first invoke() call must pause at Human Approval and never
reach a final answer on its own; only a second, explicit resume call can finalize it.
"""

import uuid

from langgraph.types import Command

from agents.graph import get_compiled_graph
from agents.runner import get_pending_interrupt
from database.db import SessionLocal


def _invoke(query: str, cards_owned: list[str], config: dict) -> dict:
    graph = get_compiled_graph()
    return graph.invoke(
        {"user_query": query, "cards_owned": cards_owned, "point_valuation": 1.0}, config=config
    )


def _mock_transfer_intent(
    mock_intent_classification, partner_name: str, miles: float = 10_000
) -> None:
    mock_intent_classification(
        intent="transfer_evaluation",
        confidence=0.95,
        spend_items=[],
        transfer_partner_name=partner_name,
        transfer_miles_amount=miles,
    )


class TestTransferApprovalGate:
    def test_evaluate_pauses_at_approval_and_never_auto_finalizes(self, mock_intent_classification):
        _mock_transfer_intent(mock_intent_classification, "Singapore Airlines KrisFlyer")
        db = SessionLocal()
        try:
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id, "db": db}}
            result = _invoke(
                "Should I transfer 10000 miles to Singapore Airlines KrisFlyer?",
                ["Axis Atlas"],
                config,
            )

            interrupt_payload = get_pending_interrupt(result)
            assert interrupt_payload is not None, "expected the graph to pause for approval"
            assert interrupt_payload["type"] == "transfer_approval_required"
            proposal = interrupt_payload["proposal"]
            assert proposal["partner_name"] == "Singapore Airlines KrisFlyer"

            # Critical safety assertion: no final_answer exists yet - nothing was finalized.
            assert "final_answer" not in result or result.get("final_answer") is None

            snapshot = get_compiled_graph().get_state(config)
            assert "human_approval" in snapshot.next
        finally:
            db.close()

    def test_confirm_approved_finalizes_the_transfer(
        self, mock_intent_classification, mock_final_answer_llm
    ):
        _mock_transfer_intent(mock_intent_classification, "Singapore Airlines KrisFlyer")
        mock_final_answer_llm("Transfer approved and processed.")
        db = SessionLocal()
        try:
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id, "db": db}}
            _invoke("Transfer 10000 miles to Singapore Airlines KrisFlyer", ["Axis Atlas"], config)

            result = get_compiled_graph().invoke(Command(resume={"approved": True}), config=config)

            assert result["approval_status"] == "approved"
            final_answer = result["final_answer"]
            assert "confirmed" in final_answer["message"].lower()
            assert (
                final_answer["transfer_proposal"]["partner_name"] == "Singapore Airlines KrisFlyer"
            )
        finally:
            db.close()

    def test_confirm_rejected_cancels_without_finalizing_a_transfer(
        self, mock_intent_classification, mock_final_answer_llm
    ):
        _mock_transfer_intent(mock_intent_classification, "Singapore Airlines KrisFlyer")
        mock_final_answer_llm("Transfer cancelled as requested.")
        db = SessionLocal()
        try:
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id, "db": db}}
            _invoke("Transfer 10000 miles to Singapore Airlines KrisFlyer", ["Axis Atlas"], config)

            result = get_compiled_graph().invoke(Command(resume={"approved": False}), config=config)

            assert result["approval_status"] == "rejected"
            assert "cancelled" in result["final_answer"]["message"].lower()
        finally:
            db.close()

    def test_unknown_transfer_partner_is_refused_before_reaching_approval(
        self, mock_intent_classification, mock_clarify_llm
    ):
        mock_intent_classification(
            intent="transfer_evaluation",
            confidence=0.9,
            spend_items=[],
            transfer_partner_name="Made-Up Frequent Flyer Program",
            transfer_miles_amount=10_000,
        )
        mock_clarify_llm("That partner isn't linked to any card you own - which one did you mean?")
        db = SessionLocal()
        try:
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id, "db": db}}
            result = _invoke(
                "Transfer 10000 miles to a made-up frequent flyer program", ["Axis Atlas"], config
            )
        finally:
            db.close()

        # Intent Classification's own partner-vocabulary guard (agents/nodes/intent.py)
        # reroutes an unrecognized partner to "unclear" before propose_transfer ever runs.
        assert get_pending_interrupt(result) is None
        assert result.get("follow_up_question")
