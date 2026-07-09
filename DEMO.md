# Demo Script

**Phase 4 deliverable** (Implementation Guide Section 3: "demo video"; acceptance criterion:
"full demo flow (ingest → query → clarify → approve → recommend) runs live without manual
intervention"). This is a step-by-step script for recording that demo - it has **not** been
recorded as an actual video file in this environment, since doing so requires a real
`ANTHROPIC_API_KEY` (unset here, see `EVALUATION_REPORT.md`'s Known Limitations) and a screen
recorder, neither of which this agent has access to. Every command below has been dry-run
against the live `docker compose` stack in this environment up to the point where a real
Claude call is required; running this script start-to-finish is the one remaining manual step.

## Before recording

1. `cp .env.example .env` and paste in a real `ANTHROPIC_API_KEY`.
2. `docker compose up -d --build` - confirm `curl http://localhost:8000/health` returns
   `{"status": "ok"}`.
3. `docker compose exec app python -m database.seed` - this **is** the "ingest" step: it
   parses the 5 real issuer PDFs in `data/raw_pdfs/`, chunks them, embeds each chunk locally,
   and stores them alongside the hand-verified `reward_rules`/`transfer_partners` rows.
   Capture this step on camera (or its terminal output) - it's part of the required flow, not
   just setup.
4. Open `http://localhost:8501` (the Streamlit UI) in the browser you'll record.
5. In the sidebar, leave the default cards (`Axis Atlas`, `Axis ACE`) or add more from
   `GET http://localhost:8000/api/v1/cards`.

## Recording script (~3-4 minutes)

### 1. Query (single-transaction recommendation)

Type into the chat: **"I am spending Rs. 50,000 on flights."**

Expected: a recommendation card for **Axis Atlas**, showing the estimated reward value,
effective return %, the calculation breakdown, and a cited excerpt from the actual PDF -
narrate that this citation and the reward number are independently verifiable, not the LLM's
guess (point at `rules_used` in the response / the "Cited —" caption in the UI).

### 2. Clarify (ambiguous query, multi-turn)

Type: **"Which card should I use?"**

Expected: the agent asks a follow-up question (e.g., "How much are you planning to spend, and
on what?") instead of guessing. Answer it in the next message (e.g., **"20000 on dining"**) -
narrate that the `session_id` under the hood is what lets the second message resolve the
first question, and that a second still-unclear answer would be met with an honest
"insufficient information" response rather than a second question (the loop cap).

### 3. Approve (Human Approval gate for a transfer)

Type: **"Should I transfer 10000 miles to Singapore Airlines KrisFlyer?"**

Expected: the chat input disappears and a **transfer proposal card** with **Confirm
transfer** / **Cancel transfer** buttons appears - narrate that nothing has been finalized
yet; the graph is genuinely paused mid-execution (a real LangGraph `interrupt()`, not a UI-
only lock), and that calling `/transfer/evaluate` again on this same session right now would
return `409 approval_pending`, not a second proposal.

Click **Confirm transfer**. Expected: a confirmation message
("Transfer confirmed: 10000 miles from Axis Atlas to Singapore Airlines KrisFlyer.") and the
chat input reopens - narrate that clicking **Cancel** instead would produce a cancellation
message with no transfer recorded, and that this is the acceptance criterion: *no transfer
calculation is ever finalized without this explicit step*.

### 4. Recommend (monthly optimization, showing multi-card allocation)

Type: **"Monthly: 50000 on flights, 4000 on utility bills, 20000 online shopping"** (or use
`POST /api/v1/optimize/monthly` directly via curl/Postman if narrating the API instead of the
UI) with at least 3 owned cards.

Expected: an allocation across categories, each with its own recommended card and cited
value - narrate that this is the same deterministic calculator and citation mechanism as
step 1, just run once per category.

### 5. (Optional, for a technical audience) Show the safety net

Run the red-team guardrail test live in a terminal to show the safety mechanism isn't just a
claim. `tests/` isn't part of the runtime container image (it's dev-only, per
`requirements-dev.txt`), so run this from the repo root with the local dev venv set up
(`pip install -r requirements-dev.txt`, pointed at the same `db` the `docker compose` stack
is using, per "Local development (without Docker)" in `README.md`):

```bash
.venv/Scripts/python -m pytest tests/agent/test_guardrail.py::TestRedTeamInventedRule -v
.venv/Scripts/python -m pytest tests/agent/test_prompt_injection_security.py -v
```

Narrate: these inject a wrong reward rate/value and a poisoned citation respectively, and the
Guardrail node - deterministic code, not another LLM call - blocks both before they could
ever reach a user.

## After recording

- Trim to the flow above; 3-5 minutes is enough to hit every acceptance-criterion beat
  (ingest, query, clarify, approve, recommend) without padding.
- If narrating live, have this file open as your cue sheet rather than reading a full script -
  the acceptance criterion is that the flow *runs live without manual intervention* (no
  restarting the stack, no hand-editing the database mid-demo), not that the narration is
  polished.
