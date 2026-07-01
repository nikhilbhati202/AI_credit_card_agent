"""LangGraph graph assembly (guide Section 14). Node functions live in agents/nodes/ and are
individually unit-tested (Section 13.1's bottom-up order); this module only wires them
together with the routing/loop-prevention logic from Section 14.1/14.3.

    START -> intent
    intent -[unclear, round < cap]-> clarify -> END (waits for the next conversation turn)
    intent -[else]-> retrieve -> validate
    validate -[insufficient evidence]-> final_answer -> END
    validate -[sufficient]-> calculate -> compare -> final_answer -> END

Session-scoped memory (Section 10.9/13.1: "start with the simplest viable mechanism") is a
LangGraph MemorySaver checkpointer keyed by session_id/thread_id - state (including
clarification_round, so the loop cap holds across real conversation turns) persists for the
life of the process without any custom persistence code.
"""

from functools import lru_cache

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.nodes.calculate import calculate
from agents.nodes.clarify import ask_clarifying_question
from agents.nodes.compare import compare
from agents.nodes.final_answer import build_final_answer
from agents.nodes.intent import classify_intent
from agents.nodes.retrieve import retrieve
from agents.nodes.validate import validate_rules
from agents.state import MAX_CLARIFICATION_ROUNDS, AgentState


def _route_after_intent(state: AgentState) -> str:
    if (
        state.get("intent") == "unclear"
        and state.get("clarification_round", 0) < MAX_CLARIFICATION_ROUNDS
    ):
        return "clarify"
    return "retrieve"


def _route_after_validation(state: AgentState) -> str:
    if not state.get("evidence_sufficient", True):
        return "insufficient"
    return "calculate"


def build_graph() -> StateGraph[AgentState, None, AgentState, AgentState]:
    graph: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)

    graph.add_node("intent", classify_intent)
    graph.add_node("clarify", ask_clarifying_question)
    graph.add_node("retrieve", retrieve)
    graph.add_node("validate", validate_rules)
    graph.add_node("calculate", calculate)
    graph.add_node("compare", compare)
    graph.add_node("final_answer", build_final_answer)

    graph.add_edge(START, "intent")
    graph.add_conditional_edges(
        "intent", _route_after_intent, {"clarify": "clarify", "retrieve": "retrieve"}
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
    graph.add_edge("final_answer", END)

    return graph


@lru_cache
def get_compiled_graph() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Compile once and reuse - the checkpointer is process-lifetime, which is exactly the
    "session-scoped" memory tier Section 10.9 describes (not persisted across restarts;
    cross-session persistence via user_profiles.conversation_summary is a Phase 3+ concern).
    """
    return build_graph().compile(checkpointer=MemorySaver())
