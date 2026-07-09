"""Human Approval node (guide Section 10.11/14.1) - the real LangGraph interrupt/resume
primitive, not the "end the turn and re-invoke" pattern Phase 2's Clarification node uses.

`interrupt()` pauses graph execution mid-node and checkpoints exactly here; the API layer's
first call to /transfer/evaluate surfaces this pause to the client as a pending proposal. The
client's later call to /transfer/confirm resumes the SAME paused execution via
`Command(resume=...)` on the same thread_id - it does not restart the graph from START, per
Section 10.11's "the graph pauses at the approval node ... and execution resumes only on
explicit user confirmation."

Session timeout / abandonment safety (Section 9.3 edge case): if the client never calls
/transfer/confirm, the graph simply stays paused forever at this interrupt - nothing auto-
approves. There is no code path from "no response" to "approved" anywhere in this node.
"""

from typing import Any

from langgraph.types import interrupt

from agents.state import AgentState


def request_approval(state: AgentState) -> dict[str, Any]:
    decision = interrupt(
        {
            "type": "transfer_approval_required",
            "proposal": state.get("transfer_proposal"),
        }
    )
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    return {"approval_status": "approved" if approved else "rejected"}
