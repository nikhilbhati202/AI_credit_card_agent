# Intelligent Credit Card & Rewards Optimization Agent

An AI system that takes a natural-language spending scenario, retrieves the governing
reward rules for a user's owned credit cards from a corpus of issuer documents, performs
a deterministic calculation, and returns a cited, explainable recommendation.

See `Intelligent_Credit_Card_Rewards_Agent_Documentation.docx` (product/architecture) and
`Intelligent_Credit_Card_Rewards_Agent_Implementation_Guide.docx` (engineering build order)
for the full specification. This README covers what exists today and how to run it.

## Status

**Phase 1 — Vertical Slice: Single-Transaction Recommendation (MVP).** End-to-end path is
live: 5 real, official card documents are ingested, chunked, embedded locally, and stored in
pgvector; a deterministic calculator computes reward value; `POST /api/v1/recommend` returns
a cited, calculated answer. No LLM is called anywhere yet — intent/category extraction is a
deterministic placeholder that Phase 2's LangGraph Intent Classification node replaces.

Golden-set results (24 hand-curated questions, `data/golden_answers.csv`):
calculation accuracy **100%**, retrieval precision@5 **0.87** (≥0.75 target), ungrounded
numeric claims **0%**.

## Quickstart

```bash
cp .env.example .env
docker compose up -d --build
curl http://localhost:8000/health   # -> {"status": "ok"}

# Seed the 5-card MVP corpus (ingest -> chunk -> embed -> store, ~1 min first run):
docker compose exec app python -m database.seed

curl -X POST http://localhost:8000/api/v1/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "I am spending Rs. 50,000 on flights.", "cards_owned": ["Axis Atlas", "Axis ACE"]}'
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

# Point .env at a reachable Postgres instance, then:
alembic upgrade head
python -m database.seed
uvicorn backend.main:app --reload
pytest
```

## Evaluation

```bash
python -m evaluation.calculation_eval    # must be 100% (Section 18.4 gate)
python -m evaluation.rag_eval            # must be >= 0.75 (architecture doc Section 3.6)
python -m evaluation.hallucination_eval  # must be 0% ungrounded
```

## Project layout

```
backend/       FastAPI app: config, routers, app factory
database/      SQLAlchemy models, engine/session, Alembic migrations, seed.py
rag/           PDF extraction, chunking, local embedding pipeline
tools/         calculator.py, retriever.py - pure, framework-agnostic, no DB/agent coupling
services/      recommendation_service.py - composes tools + repositories (pre-agent, Phase 1)
evaluation/    golden-set harness: calculation accuracy, retrieval precision@K, grounding
data/          raw_pdfs/ (5 official card documents), golden_answers.csv
tests/         unit / integration / agent test suites
```

`agents/` is introduced in Phase 2 once a LangGraph graph actually wraps these services -
scaffolding it earlier would be the "over-engineering the skeleton" risk the implementation
guide calls out explicitly for Phase 0/1.

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
| Type checking | mypy (`--strict` on `database/models.py`, `tools/calculator.py`, `tools/retriever.py`) |
| Tests | pytest (`tests/unit`, `tests/integration`) |
| Embeddings | Local `BAAI/bge-small-en-v1.5` via sentence-transformers (no API key needed) |
| Pre-commit | Ruff + mypy + basic hygiene hooks |
| CI | GitHub Actions (`.github/workflows/ci.yml`) — spins up Postgres+pgvector, seeds, runs tests + all three evaluation gates |
