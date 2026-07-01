"""Final Answer node (guide Section 14.1) - deliberately built last (Section 13.1) so it has
every upstream signal (rules, calculation, comparison, confidence) available to reference.

Assembles the structured response (deterministic, reusing the same field shape and
confidence banding as Phase 1's recommendation_service) and adds one LLM-generated narrative
field. The narrative is explicitly constrained to explain the structured numbers, never
compute or introduce new ones (Section 15.1) - if the LLM call fails, the structured result
is still returned with a templated fallback explanation rather than failing the whole
response over a non-essential prose step.
"""

from typing import Any

from agents.llm import get_final_answer_llm
from agents.prompts.final_answer_prompt import build_final_answer_prompt
from agents.state import AgentState, CardResult
from database.models import RewardUnit as DbRewardUnit
from services.recommendation_service import confidence_label

DEFAULT_POINT_VALUATION = 1.0


def _assumptions(best: CardResult, point_valuation: float, category_was_assumed: bool) -> list[str]:
    assumptions = [
        "Monthly cap assumed unused (this transaction treated as the only spend this period)."
    ]
    if best["reward_unit"] in (DbRewardUnit.POINTS.value, DbRewardUnit.MILES.value):
        assumptions.append(f"Point/mile value assumed at Rs.{point_valuation:g} per unit.")
    if category_was_assumed:
        assumptions.append(
            "No specific accelerated spend category was recognized; the general/base "
            "reward rate ('other') was used for each card."
        )
    return assumptions


def _single_transaction_result(state: AgentState) -> dict[str, Any]:
    spend_items = state.get("spend_items", [])
    ranked = state.get("ranked_comparison", {})
    point_valuation = state.get("point_valuation", DEFAULT_POINT_VALUATION)

    if not spend_items:
        return {
            "recommended_card": None,
            "insufficient_information": True,
            "message": "I couldn't determine a spend amount and category from this query.",
        }

    category = spend_items[0]["category"]
    results = ranked.get(category, [])
    if not results:
        return {
            "spend_category": category,
            "recommended_card": None,
            "insufficient_information": True,
            "message": f"I don't have an active rule for '{category}' spend on any card you own.",
        }

    best = results[0]
    caps_or_exclusions = [r["exclusion_note"] for r in results if r["exclusion_note"]]

    if best["reward_value"] <= 0:
        return {
            "spend_category": category,
            "recommended_card": None,
            "caps_or_exclusions": caps_or_exclusions,
            "assumptions": _assumptions(best, point_valuation, False),
            "confidence": "High",
            "insufficient_information": False,
            "message": (
                f"None of your queried cards earn rewards for '{category}' spend based on "
                "retrieved evidence."
            ),
        }

    return {
        "spend_category": category,
        "recommended_card": best["card_name"],
        "estimated_reward_value": round(best["reward_value"], 2),
        "effective_return_pct": round(best["effective_return_pct"], 2),
        "calculation": {
            "spend_amount": best["spend_amount"],
            "reward_rate": best["reward_rate"],
            "reward_unit": best["reward_unit"],
            "point_valuation": point_valuation,
            "cap_applied": best["cap_applied"],
        },
        "rules_used": [r["citation"] for r in results if r["citation"]],
        "caps_or_exclusions": caps_or_exclusions,
        "assumptions": _assumptions(best, point_valuation, False),
        "alternatives": [
            {"card_name": r["card_name"], "estimated_value": round(r["reward_value"], 2)}
            for r in results[1:]
        ],
        "confidence": confidence_label(best["confidence_score"]),
        "insufficient_information": False,
        "message": None,
    }


def _monthly_optimization_result(state: AgentState) -> dict[str, Any]:
    ranked = state.get("ranked_comparison", {})
    point_valuation = state.get("point_valuation", DEFAULT_POINT_VALUATION)

    allocation = []
    total_value = 0.0
    for category, results in ranked.items():
        if not results:
            allocation.append(
                {
                    "spend_category": category,
                    "recommended_card": None,
                    "insufficient_information": True,
                }
            )
            continue
        best = results[0]
        entry: dict[str, Any] = {
            "spend_category": category,
            "spend_amount": best["spend_amount"],
            "insufficient_information": False,
        }
        if best["reward_value"] <= 0:
            entry["recommended_card"] = None
            entry["message"] = f"No card earns rewards for '{category}'."
        else:
            entry["recommended_card"] = best["card_name"]
            entry["estimated_reward_value"] = round(best["reward_value"], 2)
            entry["citation"] = best["citation"]
            total_value += best["reward_value"]
        allocation.append(entry)

    return {
        "insufficient_information": not allocation,
        "allocation": allocation,
        "total_estimated_reward_value": round(total_value, 2),
        "assumptions": [
            "Each category's spend is assumed independent (no shared/combined caps across "
            "categories tracked across a full month).",
            f"Point/mile value assumed at Rs.{point_valuation:g} per unit where applicable.",
        ],
        "message": None if allocation else "I don't have enough information for any category.",
    }


def build_final_answer(state: AgentState) -> dict[str, Any]:
    if not state.get("evidence_sufficient", True):
        structured: dict[str, Any] = {
            "insufficient_information": True,
            "message": state.get("evidence_reason", "Insufficient retrieved evidence."),
        }
    elif state.get("intent") == "monthly_optimization":
        structured = _monthly_optimization_result(state)
    else:
        structured = _single_transaction_result(state)

    try:
        prompt = build_final_answer_prompt(state["user_query"], str(structured))
        response = get_final_answer_llm().invoke(prompt)
        explanation = (
            response.content if isinstance(response.content, str) else str(response.content)
        )
        structured["explanation"] = explanation.strip()
    except Exception:  # noqa: BLE001 - prose is non-essential; never fail the response over it
        structured["explanation"] = structured.get("message") or "See the structured result above."

    return {"final_answer": structured}
