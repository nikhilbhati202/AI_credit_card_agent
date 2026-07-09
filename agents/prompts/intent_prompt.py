"""Intent classification prompt (guide Section 15.1): map query -> one of a fixed enum of
intents, via constrained/structured output rather than free text, to avoid parsing ambiguity.

This is the first LLM-dependent node in the graph (Section 13.1) - it replaces Phase 1's
deterministic services/query_parsing.py regex extraction with real natural-language
understanding, while keeping the output schema just as constrained.
"""

from services.query_parsing import CATEGORY_KEYWORDS

# "groceries" only exists for the Test Card Alpha mock card (Section 6.6) - not part of the
# real-card taxonomy shown to the LLM.
KNOWN_CATEGORIES = sorted(k for k in CATEGORY_KEYWORDS if k != "groceries") + ["other"]

INTENT_PROMPT_TEMPLATE = """Classify the following user query about credit card rewards.

Known spend categories (use one of these exact strings, or "other" if none fit):
{categories}

Known point-transfer partners for the cards this user owns (may be empty if they own no
transferable-points card, or if none apply):
{partners}

Query: {query}

Conversation context so far (may be empty): {conversation_summary}

Decide:
1. intent:
   - "single_transaction" - the user describes ONE spend (one amount, one category) and
     wants a card recommendation for it.
   - "monthly_optimization" - the user describes their MONTHLY spend broken down across
     multiple categories and wants an allocation plan across their cards.
   - "transfer_evaluation" - the user is asking whether to transfer reward points/miles to
     one of the known transfer partners above (never a partner not in that list).
   - "unclear" - you cannot confidently identify what is being asked, or the request mixes
     signals in a way that needs a follow-up question.
2. confidence: your confidence in the intent classification, 0.0-1.0.
3. spend_items: a list of {{category, amount}} pairs found in the query (only relevant for
   single_transaction/monthly_optimization). A single_transaction query has exactly one; a
   monthly_optimization query typically has several. Use amounts exactly as stated (assume
   Indian Rupees, resolve "lakh"/"k" suffixes to numbers, e.g. "2 lakh" -> 200000).
4. transfer_partner_name: only for transfer_evaluation - the exact partner name from the
   known list above. Never invent a partner not in that list.
5. transfer_miles_amount: only for transfer_evaluation - the number of miles/points the user
   wants to transfer.
6. transfer_partner_point_valuation: only for transfer_evaluation - if the user states how
   much they value a partner point/mile in Rupees (e.g. "I value KrisFlyer miles at Rs.1.5
   each"), extract that number; otherwise leave null (a default will be used and disclosed).
7. ambiguity_reason: if intent is "unclear" (or confidence is low), a short phrase describing
   what is missing or ambiguous. Otherwise leave this null.

Never invent a category, partner name, or amount that was not stated or clearly implied in
the query."""


def build_intent_prompt(
    query: str, conversation_summary: str | None, known_partners: list[str] | None = None
) -> str:
    return INTENT_PROMPT_TEMPLATE.format(
        categories=", ".join(KNOWN_CATEGORIES),
        partners=", ".join(known_partners) if known_partners else "(none)",
        query=query,
        conversation_summary=conversation_summary or "(none)",
    )
