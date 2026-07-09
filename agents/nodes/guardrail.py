"""Guardrail node (guide Section 14.1; architecture doc Section 10.12) - a dedicated,
independently unit-tested node that programmatically checks the draft answer against
retrieved evidence and the deterministic calculation, run after Final Answer drafts a
response and before it ever reaches the user.

This is a code-level check, not a prompt suffix (Section 10.12's whole argument): every
check here is deterministic and testable without any LLM involvement, so a red-team test can
inject a deliberately wrong claim and assert the guardrail catches it (Section 3's Phase 3
acceptance criterion) without needing the LLM to misbehave on cue.

Checks performed (Section 17's top risks, made concrete):
1. Numeric consistency: the winning card's reward_value/rate is independently recomputed
   from the DB and must match the draft exactly - catches "the LLM invented a reward rate
   not present in retrieved evidence."
2. Citation required: a non-excluded recommendation must cite at least one chunk - catches
   an ungrounded claim slipping through.
3. Category vocabulary: every spend_item's category must be one Intent Classification is
   actually allowed to use - catches the LLM hallucinating a category that matches no rule.
4. Prompt-injection leakage: the LLM-authored explanation must not echo instruction-like
   phrases that could only have come from ingested document text asserting authority over
   the system (Section 17's #2 risk: "never let retrieved chunk content alter system-level
   behavior").
5. Number grounding: every standalone number mentioned in the explanation prose must be
   traceable to a number already present in the structured result (Section 15.1's
   "must not introduce any number not present in the tool's output").
"""

import json
import re
from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session

from agents.prompts.intent_prompt import KNOWN_CATEGORIES
from agents.state import AgentState, SpendItem
from monitoring.custom_logger import logger
from services.recommendation_service import evaluate_card
from services.transfer_service import TransferPartnerNotFoundError, evaluate_transfer

VALUE_TOLERANCE = 0.01

_INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (the )?(above|previous)",
    r"you are now",
    r"new instructions?:",
    r"system prompt",
    r"act as (a|an) (?!edge|assistant\b)",
]


def _numbers_in(text: str) -> set[float]:
    return {float(m.replace(",", "")) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def _check_numeric_consistency(db: Session, final_answer: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    category = final_answer.get("spend_category")
    card = final_answer.get("recommended_card")
    calculation = final_answer.get("calculation")
    if not card or not category or not calculation:
        return violations

    recomputed = evaluate_card(
        db,
        card,
        category,
        calculation["spend_amount"],
        calculation.get("point_valuation", 1.0),
        retrieved=[],
    )
    if recomputed is None:
        violations.append(f"recommended card {card!r} has no DB rule for category {category!r}")
        return violations

    reported_value = final_answer.get("estimated_reward_value")
    if reported_value is None or abs(recomputed.reward_value - reported_value) > VALUE_TOLERANCE:
        violations.append(
            f"reported estimated_reward_value {reported_value} does not match the "
            f"independently recomputed value {recomputed.reward_value}"
        )
    if calculation.get("reward_rate") != recomputed.reward_rate:
        violations.append(
            f"reported reward_rate {calculation.get('reward_rate')} != DB rule "
            f"{recomputed.reward_rate}"
        )
    return violations


def _check_citation_required(final_answer: dict[str, Any]) -> list[str]:
    is_positive_recommendation = (
        final_answer.get("recommended_card")
        and (final_answer.get("estimated_reward_value") or 0) > 0
    )
    if is_positive_recommendation and not final_answer.get("rules_used"):
        return ["recommendation has no citation in rules_used"]
    return []


def _check_category_vocabulary(spend_items: list[SpendItem]) -> list[str]:
    return [
        f"spend_item category {item['category']!r} is not a known category"
        for item in spend_items
        if item["category"] not in KNOWN_CATEGORIES
    ]


def _check_injection_leakage(explanation: str) -> list[str]:
    lowered = explanation.lower()
    return [
        f"explanation contains an instruction-like phrase matching {pattern!r}"
        for pattern in _INJECTION_PATTERNS
        if re.search(pattern, lowered)
    ]


def _check_number_grounding(final_answer: dict[str, Any], explanation: str) -> list[str]:
    grounded: set[float] = set()
    for key in ("estimated_reward_value", "effective_return_pct", "total_estimated_reward_value"):
        value = final_answer.get(key)
        if isinstance(value, int | float):
            grounded.add(round(float(value), 2))
            grounded.add(round(float(value)))
    calculation = final_answer.get("calculation") or {}
    for key in (
        "spend_amount",
        "reward_rate",
        "point_valuation",
        "reward_units_earned",
        "uncapped_reward_value",
    ):
        value = calculation.get(key)
        if isinstance(value, int | float):
            grounded.add(round(float(value), 2))
            grounded.add(round(float(value)))
    for allocation_entry in final_answer.get("allocation") or []:
        for key in (
            "spend_amount",
            "estimated_reward_value",
            "reward_rate",
            "reward_units_earned",
            "uncapped_reward_value",
        ):
            value = allocation_entry.get(key)
            if isinstance(value, int | float):
                grounded.add(round(float(value), 2))
                grounded.add(round(float(value)))

    violations = []
    for number in _numbers_in(explanation):
        if number in (0, 1, 100) or any(abs(number - g) < 0.5 for g in grounded):
            continue
        # A model sometimes writes a percentage as a fraction (e.g. "0.04" for "4%") instead
        # of matching the grounded value's own scale - treat that as the same number, not a
        # new one, rather than penalizing a formatting choice as if it were ungrounded.
        if any(abs(number * 100 - g) < 0.5 for g in grounded):
            continue
        violations.append(
            f"explanation mentions {number} which is not present in the structured result"
        )
    return violations


def _deterministic_explanation(final_answer: dict[str, Any]) -> str:
    """A guaranteed-safe explanation built entirely from already-validated structured fields,
    no LLM involved. Used whenever the LLM's narrative fails a safety check but the
    recommendation itself (numbers, citation, category) was independently verified correct -
    Section 24's principle applied literally: never discard a correct recommendation just
    because its prose was unreliable, when a safe substitute is this cheap to construct.
    """
    allocation = final_answer.get("allocation")
    if allocation is not None:
        parts = []
        for entry in allocation:
            if entry.get("recommended_card"):
                parts.append(
                    f"{entry['spend_category']}: {entry['recommended_card']} "
                    f"(Rs.{entry.get('estimated_reward_value', 0):,.2f})"
                )
            else:
                parts.append(f"{entry['spend_category']}: {entry.get('message', 'no reward')}")
        return "Monthly allocation - " + "; ".join(parts) + "."

    if not final_answer.get("recommended_card"):
        return final_answer.get("message") or "See the structured result above."

    calculation = final_answer.get("calculation") or {}
    sentence = (
        f"{final_answer['recommended_card']} is recommended: "
        f"{calculation.get('reward_rate', 0):g} {calculation.get('reward_unit', '')} per Rs.100 "
        f"on Rs.{calculation.get('spend_amount', 0):,.0f} spend earns an estimated "
        f"Rs.{final_answer.get('estimated_reward_value', 0):,.2f} "
        f"({final_answer.get('effective_return_pct', 0):.2f}% return)."
    )
    uncapped = calculation.get("uncapped_reward_value")
    if calculation.get("cap_applied") and uncapped is not None:
        sentence += f" A monthly cap applies - without it this would be Rs.{uncapped:,.2f}."
    return sentence


def _check_transfer_proposal_consistency(db: Session, proposal: dict[str, Any]) -> list[str]:
    """The transfer-flow analog of _check_numeric_consistency: independently recompute the
    proposal from the DB ratio and confirm it matches exactly before a human ever sees it
    for approval (FR-13's gate must be shown a verified proposal, never a guessed one).
    """
    try:
        recomputed = evaluate_transfer(
            db,
            proposal["card_name"],
            proposal["partner_name"],
            proposal["miles_amount"],
            proposal.get("partner_point_valuation")
            or (proposal["transfer_value"] / proposal["partner_units_received"]),
        )
    except (TransferPartnerNotFoundError, KeyError, ZeroDivisionError) as exc:
        return [f"could not independently verify the transfer proposal: {exc}"]

    violations = []
    if abs(recomputed.transfer_value - proposal["transfer_value"]) > VALUE_TOLERANCE:
        violations.append(
            f"reported transfer_value {proposal['transfer_value']} does not match the "
            f"independently recomputed value {recomputed.transfer_value}"
        )
    return violations


def check_guardrails(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    db: Session = config["configurable"]["db"]
    category_violations = _check_category_vocabulary(state.get("spend_items", []))

    transfer_proposal = state.get("transfer_proposal")
    final_answer_raw = state.get("final_answer")

    if transfer_proposal and not final_answer_raw:
        # Pre-approval: the proposal itself is the "draft" being checked. No retry loop for
        # transfers (Section 14.3's loop cap is a spend-flow concept - there is no
        # "retrieval" step to retry here), so the loop counter is left untouched.
        violations = category_violations + _check_transfer_proposal_consistency(
            db, transfer_proposal
        )
        return {"guardrail_passed": not violations, "guardrail_violations": violations}

    if not final_answer_raw:
        return {"guardrail_passed": True, "guardrail_violations": []}
    final_answer: dict[str, Any] = dict(final_answer_raw)  # may patch "explanation" below

    # "Core" violations mean the recommendation ITSELF can't be trusted (wrong card, wrong
    # number, missing citation, invented category) - these still go through the existing
    # retry-then-refuse loop, since retrying might genuinely produce a different result.
    core_violations = (
        category_violations
        + _check_numeric_consistency(db, final_answer)
        + _check_citation_required(final_answer)
    )

    # "Narrative" violations mean only the LLM's PROSE broke a safety check - the numbers,
    # citation, and category were already independently verified correct above. Retrying a
    # deterministic (temperature=0) model against the identical input reproduces the identical
    # mistake (confirmed empirically via guardrail_violation logs, not assumed), so looping
    # back to "retrieve" would only add latency for zero benefit.
    explanation = str(final_answer.get("explanation") or "")
    narrative_violations = _check_injection_leakage(explanation) + _check_number_grounding(
        final_answer, explanation
    )

    if not core_violations and narrative_violations:
        # Never discard an independently-verified-correct recommendation just because its
        # prose was unreliable (Section 24) - patch the explanation with a guaranteed-safe,
        # template-built one and let the response through, instead of retrying (pointless, per
        # above) or refusing (throws away a recommendation that was actually fine).
        logger.warning(
            json.dumps(
                {
                    "event": "guardrail_narrative_recovered",
                    "violations": narrative_violations,
                    "spend_category": final_answer.get("spend_category"),
                    "recommended_card": final_answer.get("recommended_card"),
                    "rejected_explanation": explanation,
                }
            )
        )
        final_answer["explanation"] = _deterministic_explanation(final_answer)
        return {
            "guardrail_passed": True,
            "guardrail_violations": [],
            "final_answer": final_answer,
        }

    violations = core_violations + narrative_violations

    # Loop-prevention (Section 14.3): every core failure here increments the counter that
    # agents/graph.py's routing checks against MAX_GUARDRAIL_LOOPS before retrying.
    loop_count = state.get("guardrail_loop_count", 0)
    if violations:
        loop_count += 1
        # WARNING for guardrail triggers (guide Section 22.4's log-level policy) - without
        # this, a refusal is diagnosable only from the violation summary, never the actual
        # rejected explanation text that caused it.
        logger.warning(
            json.dumps(
                {
                    "event": "guardrail_violation",
                    "violations": violations,
                    "loop_count": loop_count,
                    "spend_category": final_answer.get("spend_category"),
                    "recommended_card": final_answer.get("recommended_card"),
                    "calculation": final_answer.get("calculation"),
                    "explanation": explanation,
                }
            )
        )

    return {
        "guardrail_passed": not violations,
        "guardrail_violations": violations,
        "guardrail_loop_count": loop_count,
    }


def refuse_after_guardrail_failure(state: AgentState) -> dict[str, Any]:
    """Bridge node: after the guardrail loop is exhausted (or a transfer proposal fails
    verification outright), turn that into the same honest "insufficient evidence" shape
    Rule Validation uses (Section 14.1: hard-refuse rather than loop indefinitely) so
    build_final_answer's existing refusal path renders it - no separate refusal template
    to keep in sync.
    """
    violations = state.get("guardrail_violations", [])
    return {
        "evidence_sufficient": False,
        "evidence_reason": (
            "A safety check on the draft answer failed and it could not be verified: "
            + "; ".join(violations)
        ),
    }
