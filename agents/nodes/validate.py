"""Rule Validation node (guide Section 14.1): a deterministic check - "is there at least one
chunk above threshold that mentions this category" - built before any LLM-assisted layer
(Section 9.1/13.1 explicitly says build the deterministic check first; a thin LLM-assisted
layer for ambiguous cases is a later enhancement, not a Phase 2 requirement).

This node must be pure and fast (no retries needed per Section 14.1 - it's a threshold check
on data already fetched, not an external call).
"""

from typing import Any

from agents.state import AgentState


def validate_rules(state: AgentState) -> dict[str, Any]:
    retrieved_chunks = state.get("retrieved_chunks", [])

    if not retrieved_chunks:
        unrecognized = state.get("unrecognized_cards")
        if unrecognized:
            return {
                "evidence_sufficient": False,
                "evidence_reason": (
                    f"{', '.join(unrecognized)!r} doesn't match any card name in our system "
                    "exactly - card names are case- and whitespace-sensitive (e.g. "
                    "'Axis Atlas', not 'axis atlas' or 'Axis Atlas '). Check the \"Cards you "
                    'own" list and try again.'
                ),
            }
        return {
            "evidence_sufficient": False,
            "evidence_reason": (
                "No retrieved evidence above the similarity threshold for the cards you own."
            ),
        }

    return {"evidence_sufficient": True, "evidence_reason": "ok"}
