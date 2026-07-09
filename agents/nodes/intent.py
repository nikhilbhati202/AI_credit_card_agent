"""Intent Classification node (guide Section 14.1) - the first LLM-dependent component
(Section 13.1). Small, focused prompt with a constrained output schema (Pydantic model via
LangChain's structured output), never free text, to avoid parsing ambiguity.

Node contract: reads user_query + conversation_summary, writes intent/intent_confidence/
spend_items (or the transfer-specific fields, for transfer_evaluation) or pending_question if
ambiguous -> routes to Clarification if intent_confidence is below threshold, else onward
(guide Section 14.1's transition table).

Known transfer partners are looked up per-request from the DB (never a static list) so the
LLM is only ever offered partners that actually exist for the cards the user owns - it cannot
invent a partner name any more than it can invent a spend category.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.llm import LLMUnavailableError, get_intent_llm
from agents.prompts.intent_prompt import build_intent_prompt
from agents.prompts.system_prompt import SYSTEM_PROMPT
from agents.state import AgentState, Intent
from database.models import TransferPartner

# Below this confidence, route to Clarification rather than guess (Section 14.1). Tuned
# empirically against the golden set, same discipline as the retrieval similarity threshold.
INTENT_CONFIDENCE_THRESHOLD = 0.6

_MALFORMED_OUTPUT_QUESTION = (
    "I couldn't quite pick out an amount and category from that - could you restate it, "
    "e.g. 'I'm spending Rs. 5,000 on groceries'?"
)

_NO_AMOUNT_STATED_REASON = (
    "No specific spend amount was stated in the message, but one was extracted anyway - "
    "please restate the amount explicitly."
)


class SpendItemModel(BaseModel):
    category: str = Field(description="one of the known spend categories, or 'other'")
    amount: float = Field(gt=0)


class IntentClassificationResult(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    spend_items: list[SpendItemModel] = Field(default_factory=list)
    transfer_partner_name: str | None = None
    transfer_miles_amount: float | None = None
    transfer_partner_point_valuation: float | None = None
    ambiguity_reason: str | None = None


def _no_digits_anywhere(*texts: str | None) -> bool:
    return not any(char.isdigit() for text in texts if text for char in text)


def _known_transfer_partners(db: Session, cards_owned: list[str]) -> list[str]:
    if not cards_owned:
        return []
    rows = db.execute(
        select(TransferPartner.partner_name)
        .where(TransferPartner.card_name.in_(cards_owned))
        .distinct()
    ).scalars()
    return sorted(rows)


def classify_intent(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    query = state["user_query"]
    conversation_summary = state.get("conversation_summary")
    db: Session = config["configurable"]["db"]
    known_partners = _known_transfer_partners(db, state.get("cards_owned", []))

    llm = get_intent_llm().with_structured_output(IntentClassificationResult)
    prompt = build_intent_prompt(query, conversation_summary, known_partners)

    try:
        result = llm.invoke([("system", SYSTEM_PROMPT), ("human", prompt)])
    except ValidationError:
        # The model responded, but its tool-call arguments don't satisfy
        # IntentClassificationResult's schema (e.g. a spend item with a missing amount) - a
        # known characteristic of smaller/self-hosted models using function-calling structured
        # output rather than strict schema-enforced decoding (see COLAB_SETUP.md's
        # troubleshooting table). This is a signal quality problem, not an API failure: treat
        # it the same as genuine low-confidence output (Section 14.1) and ask for
        # clarification, rather than failing the whole request as a 503.
        return {
            "intent": "unclear",
            "intent_confidence": 0.0,
            "spend_items": [],
            "pending_question": _MALFORMED_OUTPUT_QUESTION,
        }
    except Exception as exc:  # noqa: BLE001 - any other LLM/API failure maps to one clear error
        raise LLMUnavailableError(f"Intent classification failed: {exc}") from exc

    assert isinstance(result, IntentClassificationResult)

    if result.spend_items and _no_digits_anywhere(query, conversation_summary):
        # Never trust an extracted spend amount that isn't traceable to something the user
        # actually typed (the same "never let an LLM introduce a number the source doesn't
        # support" principle the Guardrail node applies to the final answer, Section 10.12 -
        # applied here to the model's OWN extraction, since smaller/self-hosted models via
        # function-calling structured output have been observed inventing a plausible-looking
        # amount rather than recognizing one was never given, see COLAB_SETUP.md).
        result = result.model_copy(
            update={
                "intent": "unclear",
                "spend_items": [],
                "ambiguity_reason": _NO_AMOUNT_STATED_REASON,
            }
        )

    if (
        result.intent == "transfer_evaluation"
        and known_partners
        and result.transfer_partner_name not in known_partners
    ):
        result = result.model_copy(
            update={
                "intent": "unclear",
                "ambiguity_reason": (
                    f"'{result.transfer_partner_name}' is not a transfer partner for any "
                    "card you own."
                ),
            }
        )

    if result.intent == "unclear" or result.confidence < INTENT_CONFIDENCE_THRESHOLD:
        return {
            "intent": "unclear",
            "intent_confidence": result.confidence,
            "spend_items": [item.model_dump() for item in result.spend_items],
            "pending_question": result.ambiguity_reason or "The request is ambiguous.",
        }

    update: dict[str, Any] = {
        "intent": result.intent,
        "intent_confidence": result.confidence,
        "spend_items": [item.model_dump() for item in result.spend_items],
    }
    if result.intent == "transfer_evaluation":
        update["transfer_request"] = {
            "partner_name": result.transfer_partner_name,
            "miles_amount": result.transfer_miles_amount,
            "partner_point_valuation": result.transfer_partner_point_valuation,
        }
    return update
