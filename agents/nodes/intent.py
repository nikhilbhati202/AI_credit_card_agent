"""Intent Classification node (guide Section 14.1) - the first LLM-dependent component
(Section 13.1). Small, focused prompt with a constrained output schema (Pydantic model via
LangChain's structured output), never free text, to avoid parsing ambiguity.

Node contract: reads user_query + conversation_summary, writes intent/intent_confidence/
spend_items (or pending_question if ambiguous) -> routes to Clarification if
intent_confidence is below threshold, else Retrieval (guide Section 14.1's transition table).
"""

from typing import Any

from pydantic import BaseModel, Field

from agents.llm import LLMUnavailableError, get_intent_llm
from agents.prompts.intent_prompt import build_intent_prompt
from agents.prompts.system_prompt import SYSTEM_PROMPT
from agents.state import AgentState, Intent

# Below this confidence, route to Clarification rather than guess (Section 14.1). Tuned
# empirically against the golden set, same discipline as the retrieval similarity threshold.
INTENT_CONFIDENCE_THRESHOLD = 0.6


class SpendItemModel(BaseModel):
    category: str = Field(description="one of the known spend categories, or 'other'")
    amount: float = Field(gt=0)


class IntentClassificationResult(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    spend_items: list[SpendItemModel] = Field(default_factory=list)
    ambiguity_reason: str | None = None


def classify_intent(state: AgentState) -> dict[str, Any]:
    query = state["user_query"]
    conversation_summary = state.get("conversation_summary")

    llm = get_intent_llm().with_structured_output(IntentClassificationResult)
    prompt = build_intent_prompt(query, conversation_summary)

    try:
        result = llm.invoke([("system", SYSTEM_PROMPT), ("human", prompt)])
    except Exception as exc:  # noqa: BLE001 - any LLM/API failure maps to one clear error
        raise LLMUnavailableError(f"Intent classification failed: {exc}") from exc

    assert isinstance(result, IntentClassificationResult)

    if result.intent == "unclear" or result.confidence < INTENT_CONFIDENCE_THRESHOLD:
        return {
            "intent": "unclear",
            "intent_confidence": result.confidence,
            "spend_items": [item.model_dump() for item in result.spend_items],
            "pending_question": result.ambiguity_reason or "The request is ambiguous.",
        }

    return {
        "intent": result.intent,
        "intent_confidence": result.confidence,
        "spend_items": [item.model_dump() for item in result.spend_items],
    }
