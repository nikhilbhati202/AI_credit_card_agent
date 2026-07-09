"""Agent-level tests (guide Section 18.3): drive the compiled LangGraph graph directly,
exercising real retrieval/validation/calculation/comparison against the seeded test database,
with only the two LLM calls mocked (tests/agent/conftest.py).
"""

import uuid

from agents.graph import get_compiled_graph
from agents.state import MAX_CLARIFICATION_ROUNDS, AgentState
from database.db import SessionLocal


def _invoke(state: AgentState, db) -> AgentState:
    graph = get_compiled_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id, "db": db}}
    return graph.invoke(state, config=config)


class TestSingleTransactionFlow:
    def test_flights_query_recommends_axis_atlas(
        self, mock_intent_classification, mock_final_answer_llm
    ):
        mock_intent_classification(
            intent="single_transaction",
            confidence=0.97,
            spend_items=[{"category": "flights", "amount": 50000}],
        )
        mock_final_answer_llm("Axis Atlas is the best choice for this flight spend.")

        db = SessionLocal()
        try:
            result = _invoke(
                {
                    "user_query": "I am spending Rs. 50,000 on flights.",
                    "cards_owned": ["Axis Atlas", "Axis ACE"],
                    "point_valuation": 1.0,
                },
                db,
            )
        finally:
            db.close()

        final_answer = result["final_answer"]
        assert final_answer["recommended_card"] == "Axis Atlas"
        assert final_answer["estimated_reward_value"] == 2500.0
        assert final_answer["explanation"] == "Axis Atlas is the best choice for this flight spend."
        assert result["intent"] == "single_transaction"
        assert not result.get("follow_up_question")

    def test_fuel_query_returns_none_reward_when_all_cards_exclude_it(
        self, mock_intent_classification, mock_final_answer_llm
    ):
        mock_intent_classification(
            intent="single_transaction",
            confidence=0.95,
            spend_items=[{"category": "fuel", "amount": 2000}],
        )
        mock_final_answer_llm()

        db = SessionLocal()
        try:
            result = _invoke(
                {
                    "user_query": "Filling petrol worth Rs. 2000",
                    "cards_owned": ["Axis Atlas", "Axis ACE"],
                    "point_valuation": 1.0,
                },
                db,
            )
        finally:
            db.close()

        final_answer = result["final_answer"]
        assert final_answer["recommended_card"] is None
        assert final_answer["insufficient_information"] is False


class TestClarificationLoop:
    def test_unclear_intent_triggers_clarification_and_stops_the_turn(
        self, mock_intent_classification, mock_clarify_llm
    ):
        mock_intent_classification(
            intent="unclear", confidence=0.2, ambiguity_reason="no amount given"
        )
        mock_clarify_llm("How much are you planning to spend, and on what?")

        db = SessionLocal()
        try:
            result = _invoke(
                {
                    "user_query": "Which card should I use?",
                    "cards_owned": ["Axis Atlas"],
                    "point_valuation": 1.0,
                },
                db,
            )
        finally:
            db.close()

        assert result["follow_up_question"] == "How much are you planning to spend, and on what?"
        assert result["clarification_round"] == 1
        assert "final_answer" not in result

    def test_clarification_round_caps_at_max_and_proceeds_instead_of_looping(
        self, mock_intent_classification, mock_final_answer_llm
    ):
        # Simulate a second turn where clarification_round is already at the cap - Section
        # 14.3's loop-prevention must force the graph onward rather than asking again.
        mock_intent_classification(
            intent="unclear", confidence=0.2, ambiguity_reason="still unclear"
        )
        mock_final_answer_llm()

        db = SessionLocal()
        try:
            result = _invoke(
                {
                    "user_query": "I still don't know",
                    "cards_owned": ["Axis Atlas"],
                    "point_valuation": 1.0,
                    "clarification_round": MAX_CLARIFICATION_ROUNDS,
                },
                db,
            )
        finally:
            db.close()

        # Forced through to a final answer (best-effort or honest insufficient-information),
        # never a second follow-up question.
        assert "final_answer" in result
        assert result["final_answer"]["insufficient_information"] is True


class TestMonthlyOptimization:
    def test_allocates_across_at_least_three_categories(
        self, mock_intent_classification, mock_final_answer_llm
    ):
        mock_intent_classification(
            intent="monthly_optimization",
            confidence=0.9,
            spend_items=[
                {"category": "flights", "amount": 50000},
                {"category": "utility_bills", "amount": 4000},
                {"category": "online_shopping", "amount": 30000},
            ],
        )
        mock_final_answer_llm("Here is your monthly allocation plan.")

        db = SessionLocal()
        try:
            result = _invoke(
                {
                    "user_query": (
                        "Monthly: 50000 on flights, 4000 on utility bills, 30000 online shopping."
                    ),
                    "cards_owned": ["Axis Atlas", "Axis ACE", "SBI Cashback"],
                    "point_valuation": 1.0,
                },
                db,
            )
        finally:
            db.close()

        final_answer = result["final_answer"]
        assert len(final_answer["allocation"]) == 3
        categories = {entry["spend_category"] for entry in final_answer["allocation"]}
        assert categories == {"flights", "utility_bills", "online_shopping"}
        # Flights -> Axis Atlas, utility_bills -> Axis ACE (per Phase 1's golden set logic)
        by_category = {entry["spend_category"]: entry for entry in final_answer["allocation"]}
        assert by_category["flights"]["recommended_card"] == "Axis Atlas"
        assert by_category["utility_bills"]["recommended_card"] == "Axis ACE"
        assert final_answer["total_estimated_reward_value"] > 0


class TestSessionMemory:
    def test_clarification_round_persists_across_turns_with_same_session_id(
        self, mock_intent_classification, mock_clarify_llm, mock_final_answer_llm
    ):
        graph = get_compiled_graph()
        thread_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            config = {"configurable": {"thread_id": thread_id, "db": db}}

            mock_intent_classification(intent="unclear", confidence=0.1, ambiguity_reason="unclear")
            mock_clarify_llm("What are you spending on?")
            turn_1 = graph.invoke(
                {
                    "user_query": "help me pick a card",
                    "cards_owned": ["Axis Atlas"],
                    "point_valuation": 1.0,
                },
                config=config,
            )
            assert turn_1["clarification_round"] == 1
            assert turn_1["follow_up_question"]

            # Second turn, same thread_id: still unclear -> must NOT ask again (cap reached).
            mock_intent_classification(
                intent="unclear", confidence=0.1, ambiguity_reason="still unclear"
            )
            mock_final_answer_llm()
            turn_2 = graph.invoke(
                {
                    "user_query": "I don't know",
                    "cards_owned": ["Axis Atlas"],
                    "point_valuation": 1.0,
                },
                config=config,
            )
            assert turn_2["clarification_round"] == 1  # unchanged - loop cap held
            assert "final_answer" in turn_2
        finally:
            db.close()


class TestGuardrailLoop:
    """Phase 4 hardening (guide Section 24's Common Pitfall: "No loop-prevention caps on
    graph cycles... assuming the LLM won't loop forever"), later revised after live user
    testing showed narrative-only guardrail failures were being refused outright even when
    the underlying recommendation was independently verified correct - wasting retries against
    a deterministic (temperature=0) model that reproduces the identical mistake every attempt,
    and throwing away a good recommendation over unreliable prose (Section 24's actual
    principle). agents/nodes/guardrail.py now recovers a narrative-only failure immediately,
    with a safe, template-built explanation, rather than looping or refusing.
    """

    def test_a_persistently_ungrounded_explanation_is_recovered_immediately_not_looped(
        self, mock_intent_classification, mock_final_answer_llm
    ):
        mock_intent_classification(
            intent="single_transaction",
            confidence=0.97,
            spend_items=[{"category": "flights", "amount": 50000}],
        )
        # The recommendation itself (Axis Atlas, correct value) is untouched by this mock -
        # only the LLM-authored explanation carries an ungrounded number.
        mock_final_answer_llm("You'll also get a surprise bonus of 87654 miles!")

        db = SessionLocal()
        try:
            result = _invoke(
                {
                    "user_query": "I am spending Rs. 50,000 on flights.",
                    "cards_owned": ["Axis Atlas", "Axis ACE"],
                    "point_valuation": 1.0,
                },
                db,
            )
        finally:
            db.close()

        assert result["guardrail_passed"] is True
        # Recovered on the first pass - no retry loop was needed, since a narrative-only
        # violation doesn't touch the loop counter at all.
        assert result.get("guardrail_loop_count", 0) == 0
        final_answer = result["final_answer"]
        assert final_answer["insufficient_information"] is False
        assert final_answer["recommended_card"] == "Axis Atlas"
        assert final_answer["estimated_reward_value"] == 2500.0
        # The bad LLM sentence never reaches the user - replaced by a safe, template-built one.
        assert "surprise bonus" not in final_answer["explanation"]
        assert "87654" not in final_answer["explanation"]
        assert "Axis Atlas" in final_answer["explanation"]
