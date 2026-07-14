# Evaluation Report

**Phase 4 deliverable** (Implementation Guide Section 3: "Run the full evaluation harness,
fix regressions, write the final report"). Generated 2026-07-02 against the Phase 1-3
codebase with the 5-card real corpus + 1 mock card + 3 transfer partners seeded.

## Headline numbers

| Gate | Result | Threshold (Section 18.4) | Status |
|---|---|---|---|
| Calculation accuracy | **100.0%** (34/34) | 100% (no tolerance) | PASS |
| Monthly-optimization accuracy | **100.0%** (21/21 category allocations across 7 scenarios) | 100% (no tolerance) | PASS |
| Retrieval precision@5 | **0.908** mean, 26 scorable golden questions | ≥ 0.75 | PASS |
| Hallucination / ungrounded-claim rate | **0.0%** (0/34) | 0% (no tolerance) | PASS |

All four are re-run automatically on every CI push (`.github/workflows/ci.yml`) and block a
merge on regression (Section 18.4's non-negotiable pair: calculation accuracy and
hallucination rate). None are new to Phase 4 - they were established in Phase 1/2 and are
**unchanged** by Phase 3's guardrail/transfer/UI work, which added no new calculation or
retrieval code paths. Re-running them fresh in Phase 4 confirms no regression was introduced
by the Guardrail node, Human Approval flow, or Streamlit UI.

## Methodology

- **Golden dataset** (`data/golden_answers.csv`, `data/golden_monthly_optimization.csv`):
  41 hand-derived questions (34 single-transaction + 7 monthly-optimization scenarios
  covering 21 category allocations), written against the source PDFs independently of the
  system's behavior (Section 18.2's "do this early, not last" discipline - the set was
  started in Phase 1 and expanded through Phase 2, not authored after the fact to match
  whatever the system already produced).
- **Calculation accuracy** (`evaluation/calculation_eval.py`) and **monthly-optimization
  accuracy** (`evaluation/monthly_optimization_eval.py`) call
  `services/recommendation_service.recommend()`/the monthly equivalent directly - the
  deterministic core, bypassing the LLM entirely - and compare against hand-verified expected
  card/value/percentage with a 0.01 rupee / 0.05 percentage-point float-rounding tolerance
  (never a tolerance for actual arithmetic drift).
- **Retrieval precision@5** (`evaluation/rag_eval.py`) checks, for each golden question with
  a known expected card, what fraction of the top-5 retrieved chunks belong to that card -
  the metric this project can measure without a full relevance-judgment corpus per chunk.
- **Hallucination / grounding** (`evaluation/hallucination_eval.py`) independently
  recomputes each recommended card's reward_rate from `reward_rules` and confirms it matches
  what was reported, and that a citation is attached to every non-excluded recommendation -
  the same numeric-consistency check the Guardrail node performs on live traffic, run here
  as a batch regression gate.

All four scripts are LLM-free and cost nothing to run, including in CI on every PR that
touches `agents/`, `tools/`, or `rag/` (Section 18.4).

## Guardrail and Human Approval verification (Phase 3, re-confirmed in Phase 4)

The golden-set gates above measure the deterministic core; Phase 3 added a second layer -
the Guardrail node and Human Approval interrupt - that the golden-set harness does not
exercise (it calls the service layer directly, beneath the graph). These are instead verified
by a dedicated automated test suite, re-run clean as part of this evaluation pass:

| Test file | What it proves | Result |
|---|---|---|
| `tests/agent/test_guardrail.py` | Guardrail blocks an invented reward rate, an invented reward value, a recommendation for a non-existent rule, a missing citation, a hallucinated category, an instruction-like phrase, and an ungrounded number in the LLM's prose - all without any LLM involved (deterministic checks) | 9/9 pass |
| `tests/agent/test_transfer_flow.py` | A transfer query pauses at a real LangGraph `interrupt()` and is never finalized until an explicit `Command(resume=...)`; an unknown transfer partner is refused before ever reaching the approval gate | 4/4 pass |
| `tests/agent/test_graph.py::TestGuardrailLoop` (added Phase 4) | A **persistently** guardrail-failing answer retries up to `MAX_GUARDRAIL_LOOPS=2` times and then refuses - proving the loop-prevention cap terminates under the full compiled graph, not just in the isolated guardrail function | 1/1 pass |
| `tests/agent/test_prompt_injection_security.py` (added Phase 4) | A poisoned/adversarial retrieved chunk cannot corrupt the actual reward calculation (which is sourced from `RewardRule`, never chunk text) even though it can become citation text; and if a compromised LLM echoed injected instructions into its prose, the Guardrail node still blocks it before the user sees it | 2/2 pass |
| `tests/integration/test_transfer_endpoints.py` | `/transfer/evaluate` returns `409` on a session with an unresolved approval; `/transfer/confirm` returns `404` on an unknown session; both endpoints correctly surface `pending_approval`/`approved`/`rejected` over real HTTP | 8/8 pass |
| `tests/ui/test_streamlit_app.py` | The Streamlit UI blocks further chat input while a transfer approval is pending and only reopens it once Confirm/Cancel resolves the gate - driven headlessly via `streamlit.testing.v1.AppTest`, no browser | 9/9 pass |

**Red-team acceptance criterion (Section 3, Phase 3):** "guardrail node blocks at least one
deliberately-injected 'invented rule' test case" - satisfied by
`TestRedTeamInventedRule` in `test_guardrail.py` (3 distinct invented-rule cases, not just
one) plus the ingestion-level poisoning scenario added in Phase 4.

**Human Approval acceptance criterion (Section 3, Phase 3):** "no transfer calculation is
ever finalized without an explicit approval step observed in a trace" - satisfied
structurally (the graph literally cannot reach `final_answer` with `approval_status` set
without passing through the `human_approval` node's `interrupt()`) and verified by
`test_transfer_flow.py`'s assertion that `final_answer` is absent from the first `invoke()`
result and only appears after an explicit `Command(resume=...)`. LangSmith tracing (env-var
driven, no code change - see `monitoring/langsmith_config.py`) makes this an inspectable
trace when `LANGCHAIN_TRACING_V2`/`LANGCHAIN_API_KEY` are set; this has not been exercised
with a real LangSmith account in this environment (see Known Limitations).

## Full automated test suite

```
103 passed (51 unit, 21 integration, 22 agent, 9 ui), 0 failed
Coverage: 80% overall; 100% on the strict-typed core (tools/, database/models.py, agents/state.py)
```

`ruff check .` / `ruff format --check .`: clean. `mypy` (strict on `database/models.py`,
`tools/`, `agents/*`, plus `backend/`, `services/`, `monitoring/`, `app/streamlit_app.py`):
0 errors.

Coverage gaps are expected, not overlooked: `database/seed.py`, `rag/ingest_pdfs.py`, and
`rag/chunk_documents.py` show 0% because they are one-shot setup scripts invoked manually or
via `docker compose exec app python -m database.seed`, never imported by the pytest suite -
their correctness is instead verified by actually running them against a real database (see
Manual Verification below) and by the golden-set/retrieval-precision gates, which fail loudly
if ingestion or chunking produced bad data.

## Known Limitations

- **Update (2026-07-02): the `openai_compatible` path has now been live-verified** against a
  real Colab-hosted `qwen2.5:7b-instruct` (via Ollama + a `cloudflared` tunnel, see
  `COLAB_SETUP.md`). All three flows were exercised end-to-end through the live API with the
  real model, not mocks: a single-transaction recommendation (correct card, correct citation,
  a coherent and fully-grounded narrative with no invented numbers), an ambiguous query
  (correctly triggered a genuinely relevant clarifying question), and a transfer evaluation
  (correctly extracted the partner/amount, paused at Human Approval, and finalized cleanly on
  `/transfer/confirm`). Structured output (Intent Classification) worked correctly using
  `agents/llm.py`'s `method="function_calling"` override on every one of these calls. Latency
  was ~51s on the first (cold, model loading into GPU VRAM) call and ~4-5s on subsequent warm
  calls. This was a small number of manual spot-checks, not a full golden-set run against the
  live model - the golden-set gates above still run LLM-free by design (Section 18.4) and
  remain the CI-blocking source of truth for calculation/retrieval correctness regardless of
  which LLM endpoint is configured.
- **LangSmith tracing has not been exercised with a real account.** The integration is
  env-var driven and requires no code change, but no trace has actually been produced or
  inspected in this environment (no `LANGCHAIN_API_KEY` available here).
- **Retrieval precision@5 (0.908) has one weak case**: golden question #23 ("Shopping online
  for Rs. 30,000") scores 0.20 (1/5) because SBI Cashback's general "online spend" chunk and
  SBI SimplyCLICK's more specific chunk compete for the same query, and the corpus includes
  both cards' documents. This is a pre-existing Phase 1 characteristic (not a Phase 3/4
  regression) and does not affect calculation accuracy, since the calculator only needs the
  correct DB rule, not the single highest-ranked chunk.
- **Transfer-ratio ground truth is secondary-source, not issuer-verified** (documented in
  `TransferPartner.confidence_score`/`source_note` and `README.md`'s "Data sourcing" section)
  - the official PDF is unreachable; ratios are cross-checked across 3 independent aggregator
  sources instead.
- Expanding the golden dataset itself (e.g., adding transfer-specific or guardrail-specific
  rows) was considered and deliberately not done - the guide's own phase checklist places
  golden-set expansion at Phase 2 ("40+ questions", already met) and treats Phase 4 as the
  point to *run* the harness and fix regressions, not extend its scope. The guardrail/
  transfer/approval logic already has dedicated, more precise unit- and agent-level test
  coverage (table above) that a CSV row of (query, expected value) can't express as clearly
  for a code-level safety mechanism.
