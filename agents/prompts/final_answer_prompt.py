"""Final answer composition prompt (guide Section 15.1): produce the user-facing narrative
in the format specified by the architecture doc's Section 13.

Critical constraint (Section 15.1): "Must not introduce any number not present in the tool's
output - this prompt explains, it never computes." The structured response fields
(recommended_card, estimated_reward_value, rules_used, alternatives, etc.) are always the
deterministic values computed by tools/calculator.py and services/*_service.py; this prompt
only composes the human-readable narrative wrapped around them.
"""

FINAL_ANSWER_PROMPT_TEMPLATE = """Write a short (2-4 sentence), plain-English explanation of
this credit card reward recommendation for the user.

User's query: {query}

Structured result (already computed, ground truth):
{structured_result}

Strict rules for numbers - follow these exactly, smaller models are especially prone to
breaking them:
- The ONLY numbers you may state are ones that appear in a top-level field above (e.g.
  estimated_reward_value, effective_return_pct, calculation.spend_amount,
  calculation.reward_rate, calculation.reward_units_earned,
  calculation.uncapped_reward_value, total_estimated_reward_value, an allocation entry's own
  values).
- Never perform, show, or restate any arithmetic (e.g. "spend x rate = reward", or any
  multiplication/division) - every number you need is already computed for you; just state it
  as given. Do not "double-check" the math in your explanation.
- calculation.reward_units_earned is how many points/miles/Rs. of cashback were actually
  earned - this is NOT the same number as estimated_reward_value (the Rupee value of that),
  except when point_valuation happens to be exactly 1. NEVER state
  calculation.reward_units_earned as if it were the Rupee value, and NEVER state
  estimated_reward_value as if it were the number of points/miles earned - they answer two
  different questions ("how many did I earn" vs. "what is that worth in Rupees") and must not
  be swapped or conflated, especially when point_valuation is not 1.
- If calculation.uncapped_reward_value is present (not null), a monthly cap changed the
  outcome - mention both numbers honestly: what the reward would have been without the cap
  (uncapped_reward_value) and what it actually is after the cap (estimated_reward_value).
  If it is null/absent, no cap applied - do not mention a cap at all.
- Any "excerpt" text under rules_used/citation is background context only, to help you
  understand WHY this card was recommended - NEVER state a number that appears only inside an
  excerpt's raw text, no matter how it's framed there, unless that exact number ALSO appears
  in a top-level field above (estimated_reward_value, effective_return_pct,
  calculation.spend_amount, calculation.reward_rate, total_estimated_reward_value, or an
  allocation entry's own values). This includes, but is not limited to:
    - crediting timelines or dates (e.g. "within N days")
    - caps or thresholds mentioned in the T&C text
    - a DIFFERENT category's rate, used as contrast ("this card also gives N on travel, but
      since your spend is 'other'...") - describe only the one rate that applies here
    - worked examples or hypothetical illustrations in the T&C (e.g. "For example, if a
      customer spends Rs. X..." with its own made-up numbers) - these describe a hypothetical
      OTHER customer, never the real user, and must never be treated as if they apply here
  Referencing the card/category by name is fine; restating any number from the excerpt is not.

Write the explanation now. Do not repeat the raw JSON back verbatim - explain it naturally.
If recommended_card is null, explain why (insufficient information, or no card rewards this
category) using only the message/caps_or_exclusions given."""


def build_final_answer_prompt(query: str, structured_result: str) -> str:
    return FINAL_ANSWER_PROMPT_TEMPLATE.format(query=query, structured_result=structured_result)
