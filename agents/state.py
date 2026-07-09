"""Single typed state object threaded through the entire graph (guide Section 14.2).

Every node reads/writes a subset of this TypedDict; LangGraph merges each node's returned
partial dict into the running state (last-write-wins per key, the correct semantics here
since no field is an accumulating list that needs a custom reducer). This file is the
graph's schema as a reviewable artifact, not an implicit contract scattered across nodes.
"""

from typing import Literal, TypedDict

Intent = Literal["single_transaction", "monthly_optimization", "transfer_evaluation", "unclear"]
ApprovalStatus = Literal["pending", "approved", "rejected"]

# Loop caps (Section 14.3): both loops in the graph must have a hard iteration cap enforced
# in state, never just an assumption that the LLM "won't" loop forever.
MAX_CLARIFICATION_ROUNDS = 1
# Raised from 2: live testing against a smaller self-hosted model (see COLAB_SETUP.md) showed
# a higher rate of Guardrail-triggered narrative failures (arithmetic restated wrong, excerpt
# details mined) than expected from a commercial API - one extra retry meaningfully improves
# the odds of eventually getting a compliant response before giving up and refusing outright.
MAX_GUARDRAIL_LOOPS = 3


class SpendItem(TypedDict):
    """One (category, amount) pair - a single-transaction query has exactly one; a
    monthly-optimization query has one per category in the user's monthly breakdown.
    """

    category: str
    amount: float


class CardResult(TypedDict):
    """One card's calculated outcome for one SpendItem - the atomic unit the Comparison
    node ranks and the Final Answer node cites.
    """

    card_name: str
    spend_category: str
    spend_amount: float
    reward_value: float
    effective_return_pct: float
    cap_applied: bool
    reward_rate: float
    reward_unit: str
    base_reward_units: float  # points/miles/Rs. actually earned - independent of point_valuation
    uncapped_reward_value: float | None  # what reward_value would be with no cap
    exclusion_flag: bool
    exclusion_note: str | None
    confidence_score: float
    citation: dict[str, object] | None


class AgentState(TypedDict, total=False):
    # --- input ---
    user_query: str
    session_id: str | None
    cards_owned: list[str]
    point_valuation: float
    conversation_summary: str | None

    # --- Intent Classification node ---
    intent: Intent
    intent_confidence: float
    spend_items: list[SpendItem]

    # --- Clarification node / loop ---
    pending_question: str | None
    follow_up_question: str | None
    clarification_round: int

    # --- Retrieval / Rule Validation nodes ---
    retrieved_chunks: list[dict[str, object]]
    unrecognized_cards: list[str]
    evidence_sufficient: bool
    evidence_reason: str

    # --- Calculation / Comparison nodes ---
    card_results: list[CardResult]
    ranked_comparison: dict[str, list[CardResult]]  # keyed by spend_category

    # --- Final Answer node ---
    final_answer: dict[str, object]

    # --- Guardrail node (Section 14.1) ---
    guardrail_passed: bool
    guardrail_violations: list[str]
    guardrail_loop_count: int

    # --- Transfer evaluation + Human Approval (Section 10.11/14.1) ---
    transfer_request: dict[str, object]  # card_name, partner_name, miles_amount, ...
    transfer_proposal: dict[str, object]
    approval_status: ApprovalStatus | None

    # --- error surfacing (Section 12.2: system failures -> 503, never silent) ---
    error: str | None
