"""Clarification node (guide Section 14.1). Generates exactly one follow-up question when
Intent Classification's confidence is too low to act on.

This node ends the current turn - the API returns the follow-up question to the caller, who
is expected to call again with the same session_id and their answer as the next `query`. The
checkpointer (agents/graph.py) makes `clarification_round` persist across that gap, which is
what makes the Section 14.3 loop cap enforceable across real conversation turns rather than
within a single synchronous call.
"""

from typing import Any

from agents.llm import LLMUnavailableError, get_intent_llm
from agents.prompts.clarify_prompt import build_clarify_prompt
from agents.state import AgentState


def ask_clarifying_question(state: AgentState) -> dict[str, Any]:
    query = state["user_query"]
    ambiguity_reason = state.get("pending_question") or "The request is ambiguous."
    round_num = state.get("clarification_round", 0) + 1

    prompt = build_clarify_prompt(query, ambiguity_reason)
    try:
        response = get_intent_llm().invoke(prompt)
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailableError(f"Clarification generation failed: {exc}") from exc

    question = response.content if isinstance(response.content, str) else str(response.content)

    return {
        "clarification_round": round_num,
        "follow_up_question": question.strip(),
    }
