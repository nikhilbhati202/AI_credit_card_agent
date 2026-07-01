"""Comparison node (guide Section 14.1): ranks calculation_results per spend_category.

Pure arithmetic (sort by reward_value), no LLM involved - Section 13.1 allows "a thin LLM
layer for ranking/formatting" but the arithmetic core is what must exist first, and a plain
sort is both sufficient and more trustworthy than delegating ranking to an LLM when the
values are already exact. Single-category, single-card cases fall out naturally (a
one-element list needs no special-casing).
"""

from typing import Any

from agents.state import AgentState, CardResult


def compare(state: AgentState) -> dict[str, Any]:
    card_results = state.get("card_results", [])

    ranked: dict[str, list[CardResult]] = {}
    for result in card_results:
        ranked.setdefault(result["spend_category"], []).append(result)

    for category_results in ranked.values():
        category_results.sort(key=lambda r: r["reward_value"], reverse=True)

    return {"ranked_comparison": ranked}
