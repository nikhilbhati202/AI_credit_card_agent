"""Thin invocation helper shared by the /recommend and /optimize/monthly endpoints - both
run the same compiled graph (guide Section 3 Phase 2: "Replace the single-shot pipeline with
a LangGraph agent"), differing only in the query they hand it.

Session continuity: when the same session_id is reused after a Clarification turn, the prior
turn's query + follow-up question are folded into conversation_summary before invoking again,
so Intent Classification has the context needed to resolve the original ambiguity (Section
14.1's "Clarification -> back to Intent Classification once user responds").
"""

import uuid
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from sqlalchemy.orm import Session

from agents.graph import get_compiled_graph
from agents.state import AgentState


def get_pending_interrupt(result: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the Human Approval interrupt payload, if the graph paused there (Section
    10.11: the graph pauses mid-execution, not "ends the turn" the way Clarification does).
    """
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    payload = interrupts[0].value
    return cast(dict[str, Any], payload)


def run_agent(
    db: Session,
    query: str,
    cards_owned: list[str],
    point_valuation: float,
    session_id: str | None,
) -> tuple[dict[str, Any], str]:
    """Invoke the graph for one conversation turn.

    Returns (final_state, session_id) - the caller should return session_id to the client so
    a follow-up turn (e.g. answering a clarifying question, or /transfer/confirm resuming a
    paused approval) can reuse it. `final_state` may contain "__interrupt__" if the graph
    paused at Human Approval instead of reaching END.
    """
    graph = get_compiled_graph()
    thread_id = session_id or str(uuid.uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": thread_id, "db": db}}

    conversation_summary = None
    if session_id is not None:
        snapshot = graph.get_state(config)
        prior = snapshot.values if snapshot else {}
        if prior.get("follow_up_question"):
            conversation_summary = (
                f"User previously asked: {prior.get('user_query', '')!r}. "
                f"System asked for clarification: {prior.get('follow_up_question', '')!r}. "
                f"User's reply: {query!r}."
            )

    initial_state: AgentState = {
        "user_query": query,
        "cards_owned": cards_owned,
        "point_valuation": point_valuation,
        "conversation_summary": conversation_summary,
        "follow_up_question": None,
    }

    result = cast(dict[str, Any], graph.invoke(initial_state, config=config))
    return result, thread_id


def has_pending_approval(db: Session, session_id: str) -> bool:
    """True if this session's graph is paused at Human Approval (Section 13's 409 case for
    /transfer/evaluate: a session with an unresolved approval must go through
    /transfer/confirm before a new transfer request can be evaluated on it).
    """
    graph = get_compiled_graph()
    config: RunnableConfig = {"configurable": {"thread_id": session_id, "db": db}}
    snapshot = graph.get_state(config)
    return bool(snapshot and "human_approval" in snapshot.next)


def resume_agent(db: Session, session_id: str, approved: bool) -> dict[str, Any]:
    """Resume a graph paused at Human Approval (guide Section 10.11) - this is a true
    LangGraph resume of the SAME paused execution, never a fresh run from START.

    Raises:
        ValueError: if there is no pending approval for this session_id (Section 13's 409
            case - the caller should map this to HTTP 409, not silently proceed).
    """
    graph = get_compiled_graph()
    config: RunnableConfig = {"configurable": {"thread_id": session_id, "db": db}}

    snapshot = graph.get_state(config)
    if not snapshot or "human_approval" not in snapshot.next:
        raise ValueError(f"No pending transfer approval for session_id={session_id!r}")

    result = cast(
        dict[str, Any], graph.invoke(Command(resume={"approved": approved}), config=config)
    )
    return result
