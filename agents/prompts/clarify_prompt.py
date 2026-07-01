"""Clarification prompt (guide Section 15.1): generate exactly one focused follow-up
question - explicitly not a list, to keep the conversation moving in a single round
(Section 14.3: max 1 clarification round before proceeding with the broadest reasonable
interpretation).
"""

CLARIFY_PROMPT_TEMPLATE = """The user asked a credit-card-rewards question that was too
ambiguous to act on.

Query: {query}
What's ambiguous: {ambiguity_reason}

Write exactly ONE short, specific follow-up question (a single sentence, no numbered lists)
that would resolve this ambiguity. Do not answer the original question."""


def build_clarify_prompt(query: str, ambiguity_reason: str) -> str:
    return CLARIFY_PROMPT_TEMPLATE.format(query=query, ambiguity_reason=ambiguity_reason)
