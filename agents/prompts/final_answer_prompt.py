"""Final answer composition prompt (guide Section 15.1): produce the user-facing narrative
in the format specified by the architecture doc's Section 13.

Critical constraint (Section 15.1): "Must not introduce any number not present in the tool's
output - this prompt explains, it never computes." The structured response fields
(recommended_card, estimated_reward_value, rules_used, alternatives, etc.) are always the
deterministic values computed by tools/calculator.py and services/*_service.py; this prompt
only composes the human-readable narrative wrapped around them.
"""

FINAL_ANSWER_PROMPT_TEMPLATE = """Write a short (2-4 sentence), plain-English explanation of
this credit card reward recommendation for the user. Reference only the numbers given below -
do not compute, round differently, or introduce any figure not present in this data.

User's query: {query}

Structured result (already computed, ground truth):
{structured_result}

Write the explanation now. Do not repeat the raw JSON back verbatim - explain it naturally.
If recommended_card is null, explain why (insufficient information, or no card rewards this
category) using only the message/caps_or_exclusions given."""


def build_final_answer_prompt(query: str, structured_result: str) -> str:
    return FINAL_ANSWER_PROMPT_TEMPLATE.format(query=query, structured_result=structured_result)
