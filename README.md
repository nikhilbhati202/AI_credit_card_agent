# Intelligent Credit Card & Rewards Optimization Agent

An AI system that takes a natural-language spending scenario, retrieves the governing
reward rules for a user's owned credit cards from a corpus of issuer documents, performs
a deterministic calculation, and returns a cited, explainable recommendation.

See `Intelligent_Credit_Card_Rewards_Agent_Documentation.docx` (product/architecture) and
`Intelligent_Credit_Card_Rewards_Agent_Implementation_Guide.docx` (engineering build order)
for the full specification. This README covers what exists today and how to run it.

## Status

**Phase 2 — Vertical Slice: Orchestration, Memory, Monthly Optimization.** The single-shot
Phase 1 pipeline is now a LangGraph agent: Intent Classification (Claude) → Clarification
(loop-capped) → Retrieval → Rule Validation → Calculation → Comparison → Final Answer.
Session-scoped conversation memory persists stated preferences across turns via a LangGraph
checkpointer. A new monthly-optimization use case allocates a multi-category monthly spend
description across ≥3 owned cards in one call. `user_profiles` is wired up for real
(`GET`/`PUT /api/v1/user/profile`), and `GET /api/v1/cards` lists the seeded corpus.

Only two nodes touch an LLM (Intent Classification, Final Answer's narrative) - retrieval,
validation, calculation, and comparison remain fully deterministic, per the project's core
thesis that arithmetic and facts must never depend on generation (Section 1.2).

Golden-set results: **34** single-transaction questions (100% calculation accuracy) + **7**
monthly-optimization scenarios (100% across 21 category-allocation checks) = **41** golden
questions, **0.91** retrieval precision@5 (≥0.75 target), **0%** ungrounded numeric claims.

## Quickstart

```bash
cp .env.example .env
# Paste your ANTHROPIC_API_KEY into .env - required from Phase 2 onward.

docker compose up -d --build
curl http://localhost:8000/health   # -> {"status": "ok"}

# Seed the 5-card MVP corpus (ingest -> chunk -> embed -> store, ~1 min first run):
docker compose exec app python -m database.seed

curl -X POST http://localhost:8000/api/v1/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "I am spending Rs. 50,000 on flights.", "cards_owned": ["Axis Atlas", "Axis ACE"]}'

curl -X POST http://localhost:8000/api/v1/optimize/monthly \
  -H "Content-Type: application/json" \
  -d '{"query": "Monthly: 50000 on flights, 4000 on utility bills, 20000 online shopping", "cards_owned": ["Axis Atlas", "Axis ACE", "SBI Cashback"]}'
```

This brings up two containers:

- `db` — Postgres 16 with the `pgvector` extension.
- `app` — the FastAPI backend. On startup it runs `alembic upgrade head` against `db`,
  then serves on port 8000.

## Local development (without Docker)

```bash
python -m venv .venv
.venv/Scripts/activate            # .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
pre-commit install

# Point .env at a reachable Postgres instance and set ANTHROPIC_API_KEY, then:
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
for the same reason - a real Anthropic key is only needed to actually run the live app.

## Multi-turn conversations

`POST /api/v1/recommend` and `/api/v1/optimize/monthly` return a `session_id`. If the query
is ambiguous, the response contains a `follow_up_question` instead of a recommendation -
call the same endpoint again with the same `session_id` and your answer as the next `query`
to continue. The clarification loop is capped at 1 round (Section 14.3): a second unclear
response is met with a best-effort or honest "insufficient information" answer, never a
second question.

## Project layout

```
backend/       FastAPI app: config, routers, app factory
database/      SQLAlchemy models, engine/session, Alembic migrations, seed.py
rag/           PDF extraction, chunking, local embedding pipeline
tools/         calculator.py, retriever.py - pure, framework-agnostic, no DB/agent coupling
services/      recommendation_service.py, user_profile_service.py - composed by the graph
agents/        LangGraph state/nodes/prompts/graph - Intent Classification through Final Answer
monitoring/    structured JSON request logging + LangSmith env-var documentation
evaluation/    golden-set harness: calculation accuracy, monthly optimization, retrieval, grounding
data/          raw_pdfs/ (5 official card documents), golden_answers.csv, golden_monthly_optimization.csv
tests/         unit / integration / agent test suites (agent tests drive the compiled graph directly)
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

## Tooling

| Concern | Tool |
|---|---|
| Dependency pinning | `pip-tools` (`requirements.in` / `requirements-dev.in` -> compiled `.txt`) |
| Lint & format | Ruff |
| Type checking | mypy (`--strict` on `database/models.py`, `tools/`, `agents/*`) |
| Tests | pytest (`tests/unit`, `tests/integration`, `tests/agent`) |
| Embeddings | Local `BAAI/bge-small-en-v1.5` via sentence-transformers (no API key needed) |
| LLM | Anthropic Claude (`claude-haiku-4-5` for Intent Classification, `claude-sonnet-5` for Final Answer narrative) |
| Orchestration | LangGraph (`agents/graph.py`), session memory via its `MemorySaver` checkpointer |
| Tracing | LangSmith, auto-enabled via `LANGCHAIN_TRACING_V2`/`LANGCHAIN_API_KEY` env vars (see `monitoring/langsmith_config.py`) |
| Pre-commit | Ruff + mypy + basic hygiene hooks |
| CI | GitHub Actions (`.github/workflows/ci.yml`) — spins up Postgres+pgvector, seeds, runs tests + all four evaluation gates (no API key needed) |
