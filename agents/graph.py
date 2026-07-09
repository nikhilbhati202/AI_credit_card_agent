"""LangGraph graph assembly (guide Section 14). Node functions live in agents/nodes/ and are
individually unit-tested (Section 13.1's bottom-up order); this module only wires them
together with the routing/loop-prevention logic from Section 14.1/14.3.

Spend flow (single_transaction / monthly_optimization):
    START -> intent
    intent -[unclear, round < cap]-> clarify -> END (waits for the next conversation turn)
    intent -[else]-> retrieve -> validate
    validate -[insufficient]-> final_answer -> END
    validate -[sufficient]-> calculate -> compare -> final_answer -> guardrail
    guardrail -[pass]-> END
    guardrail -[fail, loop < cap]-> retrieve (regenerate)
    guardrail -[fail, loop >= cap]-> guardrail_refusal -> final_answer -> END

Transfer flow (transfer_evaluation) - FR-13's approval gate:
    intent -[transfer_evaluation]-> propose_transfer
    propose_transfer -[insufficient]-> final_answer -> END
    propose_transfer -[sufficient]-> guardrail
    guardrail -[pass]-> human_approval (real interrupt/resume, Section 10.11) -> final_answer -> END
    guardrail -[fail]-> guardrail_refusal -> final_answer -> END

Session-scoped memory (Section 10.9/13.1: "start with the simplest viable mechanism") is a
LangGraph MemorySaver checkpointer keyed by session_id/thread_id - state (including
clarification_round and guardrail_loop_count, so both loop caps hold across real turns)
persists for the life of the process without any custom persistence code.
"""

from functools import lru_cache

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.nodes.approval import request_approval
from agents.nodes.calculate import calculate
from agents.nodes.clarify import ask_clarifying_question
from agents.nodes.compare import compare
from agents.nodes.final_answer import build_final_answer
from agents.nodes.guardrail import check_guardrails, refuse_after_guardrail_failure
from agents.nodes.intent import classify_intent
from agents.nodes.retrieve import retrieve
from agents.nodes.transfer import propose_transfer
from agents.nodes.validate import validate_rules
from agents.state import MAX_CLARIFICATION_ROUNDS, MAX_GUARDRAIL_LOOPS, AgentState


def _route_after_intent(state: AgentState) -> str:
    if (
        state.get("intent") == "unclear"
        and state.get("clarification_round", 0) < MAX_CLARIFICATION_ROUNDS
    ):
        return "clarify"
    if state.get("intent") == "transfer_evaluation":
        return "propose_transfer"
    return "retrieve"


def _route_after_validation(state: AgentState) -> str:
    if not state.get("evidence_sufficient", True):
        return "insufficient"
    return "calculate"


def _route_after_transfer_proposal(state: AgentState) -> str:
    if not state.get("evidence_sufficient", True):
        return "insufficient"
    return "guardrail"


def _route_after_final_answer(state: AgentState) -> str:
    """final_answer is reached from three places: a fresh spend-flow draft (needs a
    guardrail pass), a post-approval/post-refusal transfer result, or an already-honest
    "insufficient evidence" refusal - only the first of these has an unchecked claim.
    """
    already_resolved = not state.get("evidence_sufficient", True) or state.get("approval_status")
    return "end" if already_resolved else "guardrail"


def _route_after_guardrail(state: AgentState) -> str:
    if state.get("guardrail_passed", True):
        return "approve" if state.get("intent") == "transfer_evaluation" else "end"
    if state.get("intent") == "transfer_evaluation":
        return "refuse"
    if state.get("guardrail_loop_count", 0) < MAX_GUARDRAIL_LOOPS:
        return "retry"
    return "refuse"


def build_graph() -> StateGraph[AgentState, None, AgentState, AgentState]:
    graph: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)

    graph.add_node("intent", classify_intent)
    graph.add_node("clarify", ask_clarifying_question)
    graph.add_node("retrieve", retrieve)
    graph.add_node("validate", validate_rules)
    graph.add_node("calculate", calculate)
    graph.add_node("compare", compare)
    graph.add_node("final_answer", build_final_answer)
    graph.add_node("propose_transfer", propose_transfer)
    graph.add_node("guardrail", check_guardrails)
    graph.add_node("guardrail_refusal", refuse_after_guardrail_failure)
    graph.add_node("human_approval", request_approval)

    graph.add_edge(START, "intent")
    graph.add_conditional_edges(
        "intent",
        _route_after_intent,
        {"clarify": "clarify", "retrieve": "retrieve", "propose_transfer": "propose_transfer"},
    )
    graph.add_edge("clarify", END)

    graph.add_edge("retrieve", "validate")
    graph.add_conditional_edges(
        "validate",
        _route_after_validation,
        {"insufficient": "final_answer", "calculate": "calculate"},
    )
    graph.add_edge("calculate", "compare")
    graph.add_edge("compare", "final_answer")

    graph.add_conditional_edges(
        "propose_transfer",
        _route_after_transfer_proposal,
        {"insufficient": "final_answer", "guardrail": "guardrail"},
    )

    # "final_answer" feeds into "guardrail" only for the flows that produced a checkable
    # draft (spend recommendations); the "insufficient evidence" branches above route
    # straight to END without a guardrail pass, since there is no claim to check yet.
    graph.add_conditional_edges(
        "final_answer", _route_after_final_answer, {"guardrail": "guardrail", "end": END}
    )
    graph.add_conditional_edges(
        "guardrail",
        _route_after_guardrail,
        {
            "approve": "human_approval",
            "end": END,
            "retry": "retrieve",
            "refuse": "guardrail_refusal",
        },
    )
    graph.add_edge("guardrail_refusal", "final_answer")
    graph.add_edge("human_approval", "final_answer")

    return graph


@lru_cache
def get_compiled_graph() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Compile once and reuse - the checkpointer is process-lifetime, which is exactly the
    "session-scoped" memory tier Section 10.9 describes (not persisted across restarts;
    cross-session persistence via user_profiles.conversation_summary is a Phase 3+ concern).
    """
    return build_graph().compile(checkpointer=MemorySaver())
