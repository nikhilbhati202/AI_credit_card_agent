"""Single-transaction recommendation service (Phase 1 vertical slice).

This composes repositories (direct queries against reward_rules/document_chunks) and tools
(calculator, retriever) as plain, synchronous function calls - proving the logic is correct
before Phase 2 wraps it in a LangGraph agent (guide Section 12.1, step 5). No LLM is called
anywhere in this module; query_parsing.py's deterministic extraction stands in for Phase 2's
real Intent Classification node.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import CapBasis as DbCapBasis
from database.models import DocumentChunk, RewardRule
from database.models import RewardRuleStatus as DbStatus
from database.models import RewardUnit as DbRewardUnit
from rag.embed_documents import embed_query
from services.query_parsing import extract_spend_amount, extract_spend_category
from tools.calculator import CapBasis, RewardUnit, calculate_reward
from tools.retriever import RetrievedChunk, retrieve_chunks

RETRIEVAL_TOP_K = 5

DEFAULT_POINT_VALUATION = 1.0

# Rule confidence_score -> a human-facing confidence label (architecture doc Section 13).
_CONFIDENCE_BANDS = (
    (0.95, "High"),
    (0.85, "Medium-High"),
    (0.70, "Medium"),
    (0.0, "Low"),
)


class RecommendationInputError(ValueError):
    """A validation failure that must surface as HTTP 422, never reach the calculator
    (Section 12.2's error-handling policy: validation errors are distinct from domain
    refusals).
    """


@dataclass(frozen=True)
class RuleCitation:
    card_name: str
    chunk_id: int | None
    excerpt: str
    source_url: str
    page_number: int | None
    effective_date: date


@dataclass(frozen=True)
class CardEvaluation:
    card_name: str
    reward_value: float
    effective_return_pct: float
    cap_applied: bool
    reward_rate: float
    reward_unit: str
    exclusion_flag: bool
    exclusion_note: str | None
    confidence_score: float
    citation: RuleCitation | None


@dataclass(frozen=True)
class RecommendationResult:
    spend_amount: float
    spend_category: str | None
    recommended_card: str | None
    estimated_reward_value: float | None
    effective_return_pct: float | None
    calculation: dict[str, Any] | None
    rules_used: list[dict[str, Any]] = field(default_factory=list)
    caps_or_exclusions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    confidence: str | None = None
    insufficient_information: bool = False
    message: str | None = None


def _confidence_label(score: float) -> str:
    for threshold, label in _CONFIDENCE_BANDS:
        if score >= threshold:
            return label
    return "Low"  # unreachable given the 0.0 floor band, kept for exhaustiveness


def _citation_from_retrieval(
    card_name: str, retrieved: list[RetrievedChunk]
) -> RuleCitation | None:
    """Prefer the live retriever's own top hit for this card as the citation - this is what
    keeps retrieval genuinely in the loop (and measurable via precision@K, Section 20)
    rather than only ever replaying a pre-recorded ingestion-time link.
    """
    for chunk in retrieved:  # already ordered by similarity (tools/retriever.py)
        if chunk.card_name == card_name:
            return RuleCitation(
                card_name=card_name,
                chunk_id=chunk.chunk_id,
                excerpt=chunk.chunk_text.strip(),
                source_url=chunk.source_url,
                page_number=chunk.page_number,
                effective_date=chunk.effective_date,
            )
    return None


def _citation_from_seed_link(db: Session, card_name: str, rule: RewardRule) -> RuleCitation | None:
    """Fall back to the citation hand-linked at ingestion time (database/seed.py) when live
    retrieval didn't surface a chunk for this card in the current top-K.
    """
    if rule.source_chunk_id is None:
        return None
    chunk = db.get(DocumentChunk, rule.source_chunk_id)
    if chunk is None:
        return None
    document = chunk.document
    return RuleCitation(
        card_name=card_name,
        chunk_id=chunk.id,
        excerpt=chunk.chunk_text.strip(),
        source_url=document.source_url,
        page_number=chunk.page_number,
        effective_date=document.effective_date,
    )


def _evaluate_card(
    db: Session,
    card_name: str,
    category: str,
    spend_amount: float,
    point_valuation: float,
    retrieved: list[RetrievedChunk],
) -> CardEvaluation | None:
    rule = db.execute(
        select(RewardRule).where(
            RewardRule.card_name == card_name,
            RewardRule.spend_category == category,
            RewardRule.status == DbStatus.ACTIVE,
        )
    ).scalar_one_or_none()
    if rule is None:
        return None

    result = calculate_reward(
        spend_amount=spend_amount,
        reward_rate=rule.reward_rate,
        reward_unit=RewardUnit(DbRewardUnit(rule.reward_unit).value),
        cap_basis=CapBasis(DbCapBasis(rule.cap_basis).value) if rule.cap_basis else None,
        cap_value=rule.cap_value,
        excess_reward_rate=rule.excess_reward_rate or 0.0,
        point_valuation=point_valuation,
    )

    citation = _citation_from_retrieval(card_name, retrieved) or _citation_from_seed_link(
        db, card_name, rule
    )

    return CardEvaluation(
        card_name=card_name,
        reward_value=result.reward_value,
        effective_return_pct=result.effective_return_pct,
        cap_applied=result.cap_applied,
        reward_rate=rule.reward_rate,
        reward_unit=rule.reward_unit.value,
        exclusion_flag=rule.exclusion_flag,
        exclusion_note=rule.exclusion_note,
        confidence_score=rule.confidence_score,
        citation=citation,
    )


def recommend(
    db: Session,
    query: str,
    cards_owned: list[str],
    point_valuation: float = DEFAULT_POINT_VALUATION,
) -> RecommendationResult:
    """Produce a cited, calculated recommendation for a single-transaction query.

    Raises:
        RecommendationInputError: when the query or inputs are malformed (maps to HTTP 422).
    """
    if not cards_owned:
        raise RecommendationInputError("cards_owned must contain at least one card")
    if point_valuation <= 0:
        raise RecommendationInputError("point_valuation must be positive")

    spend_amount = extract_spend_amount(query)
    if spend_amount is None:
        raise RecommendationInputError("Could not determine a spend amount from the query")
    if spend_amount <= 0:
        raise RecommendationInputError("spend_amount must be positive")

    # No specific accelerated category recognized -> fall back to each card's generic "other"
    # rate, which is what a real cardholder would actually earn, rather than refusing outright
    # (Section 12.2 reserves "insufficient information" for missing *evidence*, not for a
    # spend simply not matching a special category name).
    matched_category = extract_spend_category(query)
    category = matched_category or "other"
    category_was_assumed = matched_category is None

    retrieved = retrieve_chunks(
        db, embed_query(query), card_names=cards_owned, top_k=RETRIEVAL_TOP_K
    )

    evaluations = [
        e
        for card in cards_owned
        if (e := _evaluate_card(db, card, category, spend_amount, point_valuation, retrieved))
        is not None
    ]

    if not evaluations:
        return RecommendationResult(
            spend_amount=spend_amount,
            spend_category=category,
            recommended_card=None,
            estimated_reward_value=None,
            effective_return_pct=None,
            calculation=None,
            insufficient_information=True,
            message=(
                f"I don't have a retrieved, active rule for '{category}' spend on any of "
                f"the cards you own ({', '.join(cards_owned)}), so I won't guess."
            ),
        )

    evaluations.sort(key=lambda e: e.reward_value, reverse=True)
    best = evaluations[0]

    assumptions = [
        "Monthly cap assumed unused (this transaction treated as the only spend this period)."
    ]
    if best.reward_unit in (DbRewardUnit.POINTS.value, DbRewardUnit.MILES.value):
        assumptions.append(f"Point/mile value assumed at Rs.{point_valuation:g} per unit.")
    if category_was_assumed:
        assumptions.append(
            "No specific accelerated spend category was recognized in the query; the "
            "general/base reward rate ('other') was used for each card."
        )

    caps_or_exclusions = [e.exclusion_note for e in evaluations if e.exclusion_note]

    if best.reward_value <= 0:
        return RecommendationResult(
            spend_amount=spend_amount,
            spend_category=category,
            recommended_card=None,
            estimated_reward_value=None,
            effective_return_pct=None,
            calculation=None,
            rules_used=[_citation_dict(e) for e in evaluations if e.citation],
            caps_or_exclusions=caps_or_exclusions,
            assumptions=assumptions,
            confidence="High",
            message=(
                f"None of your queried cards earn rewards for '{category}' spend based on "
                "retrieved evidence."
            ),
        )

    alternatives = [
        {"card_name": e.card_name, "estimated_value": round(e.reward_value, 2)}
        for e in evaluations[1:]
    ]

    return RecommendationResult(
        spend_amount=spend_amount,
        spend_category=category,
        recommended_card=best.card_name,
        estimated_reward_value=round(best.reward_value, 2),
        effective_return_pct=round(best.effective_return_pct, 2),
        calculation={
            "spend_amount": spend_amount,
            "reward_rate": best.reward_rate,
            "reward_unit": best.reward_unit,
            "point_valuation": point_valuation,
            "cap_applied": best.cap_applied,
        },
        rules_used=[_citation_dict(e) for e in evaluations if e.citation],
        caps_or_exclusions=caps_or_exclusions,
        assumptions=assumptions,
        alternatives=alternatives,
        confidence=_confidence_label(best.confidence_score),
    )


def _citation_dict(evaluation: CardEvaluation) -> dict[str, Any]:
    citation = evaluation.citation
    assert citation is not None
    return {
        "card_name": citation.card_name,
        "chunk_id": citation.chunk_id,
        "excerpt": citation.excerpt,
        "source_url": citation.source_url,
        "page_number": citation.page_number,
        "effective_date": citation.effective_date.isoformat(),
    }
