"""Shared fixtures for agent-level tests (guide Section 18.3: "pytest driving the compiled
LangGraph graph directly, not through the API").

The two LLM-touching nodes (Intent Classification, Final Answer) are mocked here rather than
calling the real Anthropic API: this keeps the automated suite free, deterministic, and
runnable in CI without a paid API key as a secret. Every other node (retrieval, validation,
calculation, comparison) runs for real against the seeded test database - only the two LLM
calls are faked, so a bug in graph wiring or the deterministic nodes still surfaces here.
"""

from unittest.mock import MagicMock

import pytest

from agents.nodes.intent import IntentClassificationResult, SpendItemModel


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


@pytest.fixture
def mock_intent_classification(monkeypatch):
    """Patch the Intent Classification node's LLM to return a fixed structured result."""

    def _apply(
        intent: str = "single_transaction",
        confidence: float = 0.95,
        spend_items: list[dict] | None = None,
        ambiguity_reason: str | None = None,
        transfer_partner_name: str | None = None,
        transfer_miles_amount: float | None = None,
        transfer_partner_point_valuation: float | None = None,
    ) -> None:
        result = IntentClassificationResult(
            intent=intent,
            confidence=confidence,
            spend_items=[SpendItemModel(**item) for item in (spend_items or [])],
            ambiguity_reason=ambiguity_reason,
            transfer_partner_name=transfer_partner_name,
            transfer_miles_amount=transfer_miles_amount,
            transfer_partner_point_valuation=transfer_partner_point_valuation,
        )
        fake_structured_llm = MagicMock()
        fake_structured_llm.invoke.return_value = result
        fake_llm = MagicMock()
        fake_llm.with_structured_output.return_value = fake_structured_llm
        monkeypatch.setattr("agents.nodes.intent.get_intent_llm", lambda: fake_llm)

    return _apply


@pytest.fixture
def mock_clarify_llm(monkeypatch):
    """Patch the Clarification node's LLM to return a fixed follow-up question."""

    def _apply(question: str = "Could you clarify your spend amount and category?") -> None:
        fake_llm = MagicMock()
        fake_llm.invoke.return_value = _FakeMessage(question)
        monkeypatch.setattr("agents.nodes.clarify.get_intent_llm", lambda: fake_llm)

    return _apply


@pytest.fixture
def mock_final_answer_llm(monkeypatch):
    """Patch the Final Answer node's LLM to return a fixed narrative string."""

    def _apply(explanation: str = "This is a templated explanation for testing.") -> None:
        fake_llm = MagicMock()
        fake_llm.invoke.return_value = _FakeMessage(explanation)
        monkeypatch.setattr("agents.nodes.final_answer.get_final_answer_llm", lambda: fake_llm)

    return _apply
