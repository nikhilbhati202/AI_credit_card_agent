"""Hardening tests for real production failures observed live via Colab/Ollama's smaller
self-hosted model (qwen2.5:7b-instruct) doing function-calling structured output, which is
less reliable than Claude's tool use or OpenAI's cloud json_schema mode:

1. A tool call that doesn't satisfy IntentClassificationResult's schema at all (a spend item
   with a null amount) - must degrade to an "unclear" clarification, never a hard 503, since
   the model DID respond; this is a signal-quality problem, not an LLM/API failure.
2. A tool call that DOES satisfy the schema but invents a plausible-looking spend amount for
   a query that never stated one at all (e.g. "Which card should I use for shopping?" ->
   amount=12000) - despite the prompt explicitly saying "never invent... an amount." This is
   the same "never trust an ungrounded number" principle the Guardrail node applies to the
   final answer (Section 10.12), applied here to the model's own extraction.

See agents/nodes/intent.py's classify_intent() and COLAB_SETUP.md's troubleshooting table.
"""

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agents.llm import LLMUnavailableError
from agents.nodes.intent import IntentClassificationResult, SpendItemModel, classify_intent
from database.db import SessionLocal


def _malformed_spend_item_error() -> ValidationError:
    try:
        SpendItemModel(category="flights", amount=None)  # type: ignore[arg-type]
    except ValidationError as exc:
        return exc
    raise AssertionError("expected SpendItemModel(amount=None) to raise ValidationError")


def test_a_malformed_structured_output_asks_for_clarification_not_a_503(monkeypatch):
    fake_structured_llm = MagicMock()
    fake_structured_llm.invoke.side_effect = _malformed_spend_item_error()
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured_llm
    monkeypatch.setattr("agents.nodes.intent.get_intent_llm", lambda: fake_llm)

    db = SessionLocal()
    try:
        result = classify_intent(
            {"user_query": "which card should I use", "cards_owned": ["Axis Atlas"]},
            {"configurable": {"db": db}},
        )
    finally:
        db.close()

    assert result["intent"] == "unclear"
    assert result["spend_items"] == []
    assert "restate it" in result["pending_question"]


def test_a_genuine_api_failure_still_raises_llm_unavailable(monkeypatch):
    fake_structured_llm = MagicMock()
    fake_structured_llm.invoke.side_effect = ConnectionError("simulated network failure")
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured_llm
    monkeypatch.setattr("agents.nodes.intent.get_intent_llm", lambda: fake_llm)

    db = SessionLocal()
    try:
        with pytest.raises(LLMUnavailableError, match="Intent classification failed"):
            classify_intent(
                {"user_query": "spending 5000 on flights", "cards_owned": ["Axis Atlas"]},
                {"configurable": {"db": db}},
            )
    finally:
        db.close()


def _mock_result(monkeypatch, result: IntentClassificationResult) -> None:
    fake_structured_llm = MagicMock()
    fake_structured_llm.invoke.return_value = result
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured_llm
    monkeypatch.setattr("agents.nodes.intent.get_intent_llm", lambda: fake_llm)


def test_an_invented_amount_for_a_query_with_no_digits_is_rejected(monkeypatch):
    _mock_result(
        monkeypatch,
        IntentClassificationResult(
            intent="single_transaction",
            confidence=0.9,
            spend_items=[{"category": "online_shopping", "amount": 12000.0}],
        ),
    )

    db = SessionLocal()
    try:
        result = classify_intent(
            {
                "user_query": "Which card should I use for shopping?",
                "cards_owned": ["Axis Atlas"],
            },
            {"configurable": {"db": db}},
        )
    finally:
        db.close()

    assert result["intent"] == "unclear"
    assert result["spend_items"] == []
    assert result["pending_question"] == (
        "No specific spend amount was stated in the message, but one was extracted anyway - "
        "please restate the amount explicitly."
    )


def test_an_extracted_amount_is_kept_when_the_query_has_a_shorthand_digit(monkeypatch):
    """Regression guard: the no-digits check must not reject legitimate shorthand extractions
    (e.g. "5k" -> 5000) just because the exact extracted number doesn't appear verbatim - it
    only rejects amounts extracted from a query with NO digits anywhere.
    """
    _mock_result(
        monkeypatch,
        IntentClassificationResult(
            intent="single_transaction",
            confidence=0.9,
            spend_items=[{"category": "online_shopping", "amount": 5000.0}],
        ),
    )

    db = SessionLocal()
    try:
        result = classify_intent(
            {"user_query": "Spending 5k on shopping", "cards_owned": ["Axis Atlas"]},
            {"configurable": {"db": db}},
        )
    finally:
        db.close()

    assert result["intent"] == "single_transaction"
    assert result["spend_items"] == [{"category": "online_shopping", "amount": 5000.0}]
