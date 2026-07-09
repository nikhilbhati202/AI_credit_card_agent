# Intelligent Credit Card & Rewards Optimization Agent

An AI system that takes a natural-language spending scenario, retrieves the governing
reward rules for a user's owned credit cards from a corpus of issuer documents, performs
a deterministic calculation, and returns a cited, explainable recommendation.

See `Intelligent_Credit_Card_Rewards_Agent_Documentation.docx` (product/architecture) and
`Intelligent_Credit_Card_Rewards_Agent_Implementation_Guide.docx` (engineering build order)
for the full specification. This README covers what exists today and how to run it -
see [`ARCHITECTURE.md`](ARCHITECTURE.md) for component/data-flow diagrams,
[`EVALUATION_REPORT.md`](EVALUATION_REPORT.md) for golden-set and safety-test results,
[`DEMO.md`](DEMO.md) for the scripted end-to-end demo walkthrough, and
[`COLAB_SETUP.md`](COLAB_SETUP.md) if you'd rather run the LLM for free in a Google Colab
notebook than pay for the Anthropic API (no code change needed - just a `.env` setting).

## Status

**Phase 4 — Evaluation, Hardening, Documentation, Buffer. Submittable.** All Phase 0-3
functionality is in place: RAG-grounded single-transaction and monthly-optimization
recommendations, a LangGraph agent with session memory and clarification, a code-level
Guardrail node, a real Human Approval interrupt/resume gate for transfer strategies, and a
Streamlit UI. Phase 4 closes it out per the Implementation Guide's own acceptance criteria:
the full evaluation harness re-run clean (0% hallucination, 100% calculation accuracy), two
additional hardening tests added (a full-graph guardrail-loop-termination proof and an
ingestion-level prompt-injection red-team test), a refusal-path bug fixed (a guardrail- or
validation-triggered refusal no longer re-invokes the narrative LLM at all, closing a path
where an unvalidated LLM claim could otherwise leak into a "safe" refusal message), and a
commit-SHA-tagged rollback demonstrated end-to-end (see "Rollback" below).

See [`EVALUATION_REPORT.md`](EVALUATION_REPORT.md) for full results and methodology,
[`ARCHITECTURE.md`](ARCHITECTURE.md) for diagrams, and [`DEMO.md`](DEMO.md) for the scripted
walkthrough. Golden-set numbers are unchanged from Phase 2 (Phases 3-4 added no new
calculation or retrieval code paths, only safety/approval layers around the existing ones):
**34** single-transaction questions (100% calculation accuracy) + **7** monthly-optimization
scenarios (100% across 21 category-allocation checks) = **41** golden questions, **0.91**
retrieval precision@5 (≥0.75 target), **0%** ungrounded numeric claims. **103** automated
tests pass (51 unit, 21 integration, 22 agent, 9 UI).

## Quickstart

**Prerequisites:** Docker Desktop (or another Docker Engine + Compose v2), `git`, and a
working LLM endpoint - either a free Google Colab notebook (see
[`COLAB_SETUP.md`](COLAB_SETUP.md), no payment or account beyond a Google login required) or
an [Anthropic API key](https://console.anthropic.com/) if you'd rather use Claude. The app
starts and the automated test suite passes without either. No local Python/Postgres install
is required for this path - everything else runs inside containers. This should comfortably
clear the guide's 30-minute clean-clone target: the image build and corpus seed together took
well under 5 minutes on this machine with a warm Docker/pip cache; a fully cold machine will
be slower mainly due to `sentence-transformers`' `torch` dependency and the one-time ~130MB
embedding-model download during the first seed, both bandwidth-bound rather than compute-bound.

```bash
git clone <this-repo-url> && cd AI_credit_card_agent
cp .env.example .env
# Default (.env.example's LLM_PROVIDER=openai_compatible): follow COLAB_SETUP.md, then paste
# the tunnel URL into LLM_BASE_URL. Or set LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY instead.

docker compose up -d --build
curl http://localhost:8000/health   # -> {"status": "ok"}

# Seed the 5-card MVP corpus + transfer partners (ingest -> chunk -> embed -> store, ~1 min first run):
docker compose exec app python -m database.seed

curl -X POST http://localhost:8000/api/v1/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "I am spending Rs. 50,000 on flights.", "cards_owned": ["Axis Atlas", "Axis ACE"]}'

curl -X POST http://localhost:8000/api/v1/optimize/monthly \
  -H "Content-Type: application/json" \
  -d '{"query": "Monthly: 50000 on flights, 4000 on utility bills, 20000 online shopping", "cards_owned": ["Axis Atlas", "Axis ACE", "SBI Cashback"]}'

# Open the chat UI at http://localhost:8501
```

This brings up three containers:

- `db` — Postgres 16 with the `pgvector` extension.
- `app` — the FastAPI backend. On startup it runs `alembic upgrade head` against `db`,
  then serves on port 8000.
- `ui` — the Streamlit chat UI (port 8501), calling `app` over HTTP only.

## Local development (without Docker)

```bash
python -m venv .venv
.venv/Scripts/activate            # .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
pre-commit install

# Point .env at a reachable Postgres instance and configure an LLM provider (see Quickstart), then:
alembic upgrade head
python -m database.seed
uvicorn backend.main:app --reload
pytest
```

## Evaluation

```bash
python -m evaluation.calculation_eval            # must be 100% (Section 18.4 gate)
python -m evaluation.monthly_optimization_eval   # must be 100%
python -m evaluation.rag_eval                    # must be >= 0.75 (architecture doc Section 3.6)
python -m evaluation.hallucination_eval          # must be 0% ungrounded
```

All four run the deterministic core directly (no LLM calls), so they're free and
deterministic to run in CI. `pytest` mocks the two LLM-touching nodes (`tests/conftest.py`)
for the same reason - a configured LLM provider (Colab/Ollama or Anthropic, see Quickstart) is
only needed to actually run the live app.

## Multi-turn conversations

`POST /api/v1/recommend` and `/api/v1/optimize/monthly` return a `session_id`. If the query
is ambiguous, the response contains a `follow_up_question` instead of a recommendation -
call the same endpoint again with the same `session_id` and your answer as the next `query`
to continue. The clarification loop is capped at 1 round (Section 14.3): a second unclear
response is met with a best-effort or honest "insufficient information" answer, never a
second question.

## Transfer evaluation and Human Approval

A query like "Should I transfer 10000 miles to Singapore Airlines KrisFlyer?" is classified as
`transfer_evaluation` and routed to a dedicated proposal + guardrail + approval flow instead of
a normal recommendation:

```bash
curl -X POST http://localhost:8000/api/v1/transfer/evaluate \
  -H "Content-Type: application/json" \
  -d '{"query": "Transfer 10000 miles to Singapore Airlines KrisFlyer", "cards_owned": ["Axis Atlas"]}'
# -> {"status": "pending_approval", "session_id": "...", "proposal": {...}}

curl -X POST http://localhost:8000/api/v1/transfer/confirm \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<session_id from above>", "approved": true}'
# -> {"approval_status": "approved", "transfer_proposal": {...}, "message": "Transfer confirmed: ..."}
```

The graph pauses at a real LangGraph `interrupt()` in `agents/nodes/approval.py` - nothing is
finalized until `/transfer/confirm` sends an explicit `Command(resume=...)` into that same
paused execution. Calling `/transfer/evaluate` again on a session with an unresolved approval
returns `409 approval_pending`. A transfer-shaped query can also reach the general
`/recommend` endpoint (the same graph, same gate) - its response carries `approval_pending`
and `transfer_proposal` fields for that case, so a single chat client only needs `/recommend`
and `/transfer/confirm`, never has to guess intent client-side to pick an endpoint.

Every draft answer (spend recommendation or transfer proposal) passes through the Guardrail
node (`agents/nodes/guardrail.py`) first: numeric consistency is independently recomputed from
the DB, citations are required, spend categories are checked against a known vocabulary, and
the LLM's prose is scanned for both prompt-injection-style phrasing and numbers that don't
trace back to the structured result. A failure here refuses the answer rather than ever
guessing; see `tests/agent/test_guardrail.py`'s `TestRedTeamInventedRule` for the case where an
invented reward rate/value is deliberately injected and blocked.

## Chat UI

```bash
API_BASE_URL=http://localhost:8000/api/v1 streamlit run app/streamlit_app.py
```

(or just use the `ui` container from `docker compose up`, already pointed at `app`). The UI is
intentionally thin (Implementation Guide Section 17.1): it only calls `/recommend` and
`/transfer/confirm`, renders the structured JSON response as a card rather than dumping raw
text, and blocks further chat input with a Confirm/Cancel gate whenever a transfer proposal is
pending. An admin document-upload panel and a `/history` analytics view are listed in Section
17.1 as part of the cumulative Phase 1-3 UI scope but are not part of Phase 3's specific
deliverable list or acceptance criteria, so both are deliberately deferred rather than built
speculatively here.

## Project layout

```
app/           Streamlit UI - a thin client that only calls the API
backend/       FastAPI app: config, routers, app factory
database/      SQLAlchemy models, engine/session, Alembic migrations, seed.py
rag/           PDF extraction, chunking, local embedding pipeline
tools/         calculator.py, retriever.py, transfer_calculator.py - pure, framework-agnostic
services/      recommendation_service.py, transfer_service.py, user_profile_service.py
agents/        LangGraph state/nodes/prompts/graph - Intent Classification through Human Approval
monitoring/    structured JSON request logging + LangSmith env-var documentation
evaluation/    golden-set harness: calculation accuracy, monthly optimization, retrieval, grounding
data/          raw_pdfs/ (5 official card documents), golden_answers.csv, golden_monthly_optimization.csv
tests/         unit / integration / agent / ui test suites (agent tests drive the compiled graph
               directly; ui tests drive app/streamlit_app.py headlessly via AppTest)
```

## Data sourcing

The 5 seeded cards (Axis Atlas, Axis ACE, SBI Cashback, SBI SimplyCLICK, ICICI Amazon Pay)
are official T&C/feature documents fetched directly from each issuer's website (Section 7.1
policy: no forum/aggregator content as ground truth). Source URL and effective date for each
are recorded in `database/seed.py` and surfaced in every citation. Two of SBI's documents
don't print an explicit revision date — the fetch date is used instead, noted as a known
limitation.

## Branching model

Trunk-based: `main` is always deployable. Work happens on short-lived
`feature/<slice-name>` branches merged into `main` via PR (Implementation Guide, Section 4).

## Rollback

Every deployed `app` image is tagged with the Git commit SHA (Implementation Guide Section
20.5), so a rollback is "redeploy the previous tag," never "revert code and rebuild under
pressure." `docker-compose.yml`'s `app` service reads its tag from `APP_IMAGE_TAG`
(default `latest`):

```bash
# Build and deploy a specific commit:
APP_IMAGE_TAG=$(git rev-parse --short HEAD) docker compose build app
APP_IMAGE_TAG=$(git rev-parse --short HEAD) docker compose up -d app

# Roll back to a previously-built tag - no rebuild, the image is already local:
APP_IMAGE_TAG=<previous-sha> docker compose up -d app
```

This was demonstrated once end-to-end in this environment: `app` was built and deployed
tagged `7278618` (healthy, `GET /health` → `{"status": "ok"}`); a deliberately broken image
was then deployed under a throwaway tag to simulate a bad release (`uvicorn` failed to boot -
`ERROR: Could not import module "backend.mainn"`, `/health` unreachable); redeploying tag
`7278618` with no rebuild immediately restored `{"status": "ok"}`. The throwaway Dockerfile
and image were deleted after the demonstration - they were never part of the real build.

Cloud deployment beyond `docker compose` (a managed container service + managed Postgres,
Section 20.3) is out of scope for this capstone's local/demo deployment target.

## Tooling

| Concern | Tool |
|---|---|
| Dependency pinning | `pip-tools` (`requirements.in` / `requirements-app.in` / `requirements-dev.in` -> compiled `.txt`) |
| Lint & format | Ruff |
| Type checking | mypy (`--strict` on `database/models.py`, `tools/`, `agents/*`) |
| Tests | pytest (`tests/unit`, `tests/integration`, `tests/agent`, `tests/ui`) |
| Embeddings | Local `BAAI/bge-small-en-v1.5` via sentence-transformers (no API key needed) |
| LLM | Provider-switchable via `LLM_PROVIDER` (`agents/llm.py`): `openai_compatible` (default - any OpenAI-compatible server, e.g. Ollama in Colab, see `COLAB_SETUP.md`) or `anthropic` (`claude-haiku-4-5`/`claude-sonnet-5`) |
| Orchestration | LangGraph (`agents/graph.py`), session memory via its `MemorySaver` checkpointer, Human Approval via `interrupt()`/`Command(resume=...)` |
| UI | Streamlit (`app/streamlit_app.py`), tested headlessly via `streamlit.testing.v1.AppTest` |
| Tracing | LangSmith, auto-enabled via `LANGCHAIN_TRACING_V2`/`LANGCHAIN_API_KEY` env vars (see `monitoring/langsmith_config.py`) - traces every graph node run, including `guardrail` and `human_approval` |
| Pre-commit | Ruff + mypy + basic hygiene hooks |
| CI | GitHub Actions (`.github/workflows/ci.yml`) — spins up Postgres+pgvector, seeds, runs tests + all four evaluation gates (no API key needed) |
