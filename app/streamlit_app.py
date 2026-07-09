"""Streamlit MVP UI (guide Section 17.1) - a thin app that only calls the API; every piece of
business logic (intent classification, retrieval, calculation, guardrails, approval gating)
lives server-side in the LangGraph agent, never duplicated here.

Phase 3's explicit deliverable is "Streamlit UI with confirm/cancel buttons" (Section 3), so
this build covers exactly that vertical slice: a chat interface backed by POST /recommend,
structured recommendation-card rendering (Section 17.1: "render the structured JSON response
into a clear card layout", not a raw text dump), and a blocking Confirm/Cancel step for the
Human Approval flow via POST /transfer/confirm. Section 17.1 also lists a basic analytics view
and an admin document-upload panel as "needed" for the cumulative Phase 1-3 UI scope, but
neither is in Phase 3's deliverable list or acceptance criteria - both are deliberately
deferred rather than built speculatively here.

State management uses st.session_state only, per Section 17.2 ("sufficient for the MVP's
conversational state; do not reach for a heavier state-management library at this stage").
"""

import os
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")
# Generous enough to cover a self-hosted/Colab-tunneled model's cold start (~50-60s observed
# when Ollama has to load the model into GPU VRAM after a session restart) plus a guardrail
# retry loop invoking Final Answer's narrative LLM call up to MAX_GUARDRAIL_LOOPS+1 times in a
# single request - a commercial API is comfortably faster than this ceiling, so raising it
# costs nothing there and avoids a false "API unreachable" for a request that's just slow.
REQUEST_TIMEOUT_SECONDS = 180

st.set_page_config(page_title="Credit Card Rewards Agent", page_icon="\U0001f4b3")


def _init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("session_id", None)
    st.session_state.setdefault("pending_proposal", None)


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """POST to the API, surfacing both transport and error-envelope failures as st.error
    rather than raising - the guide's failure mode is a message field, never a crashed page.
    """
    try:
        response = requests.post(
            f"{API_BASE_URL}{path}", json=payload, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        st.error(f"Could not reach the API at {API_BASE_URL}: {exc}")
        return None
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except ValueError:
            detail = response.text
        st.error(f"API error ({response.status_code}): {detail}")
        return None
    result: dict[str, Any] = response.json()
    return result


_CITATION_PREVIEW_CHARS = 180

# reward_unit -> (earned-line label, singular unit name for the point-value line)
_UNIT_LABELS = {
    "miles": ("Miles Earned", "Mile"),
    "points": ("Points Earned", "Point"),
    "cashback": ("Cashback Earned", "Rupee"),
}


def _render_calculation_breakdown(answer: dict[str, Any], calculation: dict[str, Any]) -> None:
    """A structured, line-by-line breakdown rather than one dense sentence - every number here
    is read straight from the API response, never recomputed in the UI (Section 17.1: the UI
    stays thin), so this is exactly as trustworthy as the sentence it replaces, just easier to
    audit at a glance.
    """
    reward_unit = calculation.get("reward_unit", "")
    earned_label, unit_singular = _UNIT_LABELS.get(reward_unit, ("Units Earned", "unit"))
    units_earned = calculation.get("reward_units_earned")
    uncapped = calculation.get("uncapped_reward_value")
    final_value = answer.get("estimated_reward_value", 0)

    with st.expander("📊 Calculation", expanded=True):
        reward_rate = calculation.get("reward_rate", 0)
        st.markdown(f"- **Spend:** Rs. {calculation.get('spend_amount', 0):,.0f}")
        st.markdown(f"- **Base rate:** {reward_rate:g} {reward_unit} per Rs.100")
        if units_earned is not None:
            st.markdown(f"- **{earned_label}:** {units_earned:g} {reward_unit}")
        if calculation.get("cap_applied") and uncapped is not None:
            st.markdown(f"- **Potential value (before cap):** Rs. {uncapped:,.2f}")
            st.markdown("- **Monthly cap applied** → reduces this to the final value below")
        elif reward_unit != "cashback":
            point_valuation = calculation.get("point_valuation", 1)
            st.markdown(f"- **Point Value:** 1 {unit_singular} = Rs. {point_valuation:g}")
        st.markdown(f"- **Estimated Reward Value:** Rs. {final_value:,.2f}")
        st.markdown(f"- **Effective return:** {answer.get('effective_return_pct', 0):.2f}%")
        if reward_unit == "cashback":
            st.caption(
                "ℹ Point/mile valuation doesn't apply here - this card pays cashback, "
                "already in Rupees."
            )


def _render_citation(rule: dict[str, Any]) -> None:
    excerpt = rule.get("excerpt", "")
    card_name = rule.get("card_name", "")
    if len(excerpt) <= _CITATION_PREVIEW_CHARS:
        st.caption(f"Cited — {card_name}: “{excerpt}”")
        return
    preview = excerpt[:_CITATION_PREVIEW_CHARS].rsplit(" ", 1)[0] + "…"
    st.caption(f"Cited — {card_name}: “{preview}”")
    with st.expander(f"Full source text — {card_name}"):
        st.write(excerpt)
        st.caption(f"{rule.get('source_url', '')} (page {rule.get('page_number', '?')})")


def _render_confidence(answer: dict[str, Any], calculation: dict[str, Any]) -> None:
    """Every line here reflects a real, already-computed signal - never a claim about what the
    user said or intended, which this system has no way to verify (e.g. whether a specific
    payment method was actually used) and must not pretend to.
    """
    confidence = answer.get("confidence")
    if not confidence:
        return
    category = answer.get("spend_category")
    reasons = []
    if category and category != "other":
        reasons.append(f"✓ Matched a specific rule for '{category}'")
    elif category == "other":
        reasons.append(
            "• No category-specific reward applies - using the card's standard earning rate"
        )
    if answer.get("rules_used"):
        reasons.append("✓ Backed by a cited source document")
    if calculation.get("cap_applied"):
        reasons.append("✓ A monthly cap was found in the terms and applied")
    st.markdown(f"**Confidence: {confidence}**")
    for reason in reasons:
        st.caption(reason)


def _render_recommendation_card(answer: dict[str, Any]) -> None:
    if answer.get("insufficient_information"):
        st.warning(answer.get("message") or "Not enough information to make a recommendation.")
    elif answer.get("recommended_card"):
        st.success(f"**Recommended card: {answer['recommended_card']}**")
        left, right = st.columns(2)
        left.metric("Estimated reward value", f"Rs. {answer.get('estimated_reward_value', 0):,.2f}")
        right.metric("Effective return", f"{answer.get('effective_return_pct', 0):.2f}%")

        calculation = answer.get("calculation") or {}
        if calculation:
            _render_calculation_breakdown(answer, calculation)
        for rule in answer.get("rules_used") or []:
            _render_citation(rule)
        for note in answer.get("caps_or_exclusions") or []:
            st.caption(f"Note: {note}")
        for assumption in answer.get("assumptions") or []:
            st.caption(f"Assumption: {assumption}")
        if answer.get("alternatives"):
            with st.expander("Other cards considered"):
                for alternative in answer["alternatives"]:
                    value = alternative["estimated_value"]
                    st.write(f"{alternative['card_name']}: Rs. {value:,.2f}")
        _render_confidence(answer, calculation)
    elif answer.get("message"):
        st.info(answer["message"])
        if answer.get("estimated_reward_value") == 0:
            st.metric("Estimated reward value", "Rs. 0.00")

    if answer.get("explanation"):
        st.write(answer["explanation"])


def _render_transfer_proposal(proposal: dict[str, Any]) -> None:
    st.info(
        f"**Transfer proposal:** {proposal.get('miles_amount', 0):,.0f} miles from "
        f"{proposal.get('card_name')} to {proposal.get('partner_name')} "
        f"(ratio {proposal.get('transfer_ratio')})"
    )
    left, right = st.columns(2)
    left.metric("Transfer value", f"Rs. {proposal.get('transfer_value', 0):,.2f}")
    right.metric(
        "Direct redemption value", f"Rs. {proposal.get('direct_redemption_value', 0):,.2f}"
    )
    st.write(f"Better option: **{proposal.get('better_option')}**")
    if proposal.get("source_note"):
        confidence = proposal.get("confidence_score", 0)
        st.caption(f"Confidence {confidence:.0%} — {proposal['source_note']}")


def _render_history_message(message: dict[str, Any]) -> None:
    with st.chat_message(message["role"]):
        if message.get("kind") == "recommendation":
            _render_recommendation_card(message["content"])
        elif message.get("kind") == "transfer_proposal":
            _render_transfer_proposal(message["content"])
        else:
            st.write(message["content"])


def _handle_pending_approval() -> bool:
    """Renders the blocking Confirm/Cancel gate (Section 17.1: "must block further interaction
    until resolved, matching the interrupt/resume semantics of the backend graph"). Returns
    True while the gate is still open, so the caller knows to skip the chat input entirely.
    """
    proposal = st.session_state.pending_proposal
    if proposal is None:
        return False

    st.warning("A transfer is awaiting your approval. Confirm or cancel before continuing.")
    _render_transfer_proposal(proposal)

    confirm_col, cancel_col = st.columns(2)
    approved: bool | None = None
    if confirm_col.button("Confirm transfer", type="primary", use_container_width=True):
        approved = True
    if cancel_col.button("Cancel transfer", use_container_width=True):
        approved = False

    if approved is not None:
        result = _post(
            "/transfer/confirm",
            {"session_id": st.session_state.session_id, "approved": approved},
        )
        st.session_state.pending_proposal = None
        if result is not None:
            st.session_state.messages.append(
                {"role": "assistant", "content": result.get("message") or ""}
            )
        st.rerun()

    return True


def main() -> None:
    _init_state()
    st.title("Intelligent Credit Card Rewards Agent")

    with st.sidebar:
        st.header("Your cards")
        cards_text = st.text_area(
            "Cards you own (one per line)", value="Axis Atlas\nAxis ACE", height=100
        )
        cards_owned = [line.strip() for line in cards_text.splitlines() if line.strip()]
        point_valuation = st.number_input(
            "Point/mile valuation (Rs.)", min_value=0.01, value=1.0, step=0.1
        )
        if st.button("Reset conversation"):
            st.session_state.messages = []
            st.session_state.session_id = None
            st.session_state.pending_proposal = None
            st.rerun()

    for message in st.session_state.messages:
        _render_history_message(message)

    if _handle_pending_approval():
        return

    if not cards_owned:
        st.info("Enter at least one card you own in the sidebar to get started.")
        return

    query = st.chat_input("Ask about a purchase, monthly spend, or a miles transfer...")
    if not query:
        return

    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.write(query)

    result = _post(
        "/recommend",
        {
            "query": query,
            "cards_owned": cards_owned,
            "point_valuation": point_valuation,
            "session_id": st.session_state.session_id,
        },
    )
    if result is None:
        return

    st.session_state.session_id = result.get("session_id")

    with st.chat_message("assistant"):
        if result.get("approval_pending"):
            proposal = result.get("transfer_proposal") or {}
            st.write("This needs your approval before it can be finalized.")
            _render_transfer_proposal(proposal)
            st.session_state.messages.append(
                {"role": "assistant", "kind": "transfer_proposal", "content": proposal}
            )
            st.session_state.pending_proposal = proposal
        elif result.get("follow_up_question"):
            st.write(result["follow_up_question"])
            st.session_state.messages.append(
                {"role": "assistant", "content": result["follow_up_question"]}
            )
        else:
            _render_recommendation_card(result)
            st.session_state.messages.append(
                {"role": "assistant", "kind": "recommendation", "content": result}
            )

    if st.session_state.pending_proposal is not None:
        st.rerun()


if __name__ == "__main__":
    main()
