"""Thin invocation helper shared by the /recommend and /optimize/monthly endpoints - both
run the same compiled graph (guide Section 3 Phase 2: "Replace the single-shot pipeline with
a LangGraph agent"), differing only in the query they hand it.

Session continuity: when the same session_id is reused after a Clarification turn, the prior
turn's query + follow-up question are folded into conversation_summary before invoking again,
so Intent Classification has the context needed to resolve the original ambiguity (Section
14.1's "Clarification -> back to Intent Classification once user responds").
"""

import uuid
from typing import cast

from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session

from agents.graph import get_compiled_graph
from agents.state import AgentState


def run_agent(
    db: Session,
    query: str,
    cards_owned: list[str],
    point_valuation: float,
    session_id: str | None,
) -> tuple[AgentState, str]:
    """Invoke the graph for one conversation turn.

    Returns (final_state, session_id) - the caller should return session_id to the client so
    a follow-up turn (e.g. answering a clarifying question) can reuse it.
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

    result = cast(AgentState, graph.invoke(initial_state, config=config))
    return result, thread_id
