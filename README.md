# Intelligent Credit Card & Rewards Optimization Agent

An AI system that takes a natural-language spending scenario, retrieves the governing
reward rules for a user's owned credit cards from a corpus of issuer documents, performs
a deterministic calculation, and returns a cited, explainable recommendation.

See `Intelligent_Credit_Card_Rewards_Agent_Documentation.docx` (product/architecture) and
`Intelligent_Credit_Card_Rewards_Agent_Implementation_Guide.docx` (engineering build order)
for the full specification. This README covers what exists today and how to run it.

## Status

**Phase 0 — Foundation.** Repository, environment, CI, and an empty-but-running service
exist. No product functionality (retrieval, calculation, agent) has been built yet — that
starts in Phase 1.

## Quickstart

```bash
cp .env.example .env
docker compose up -d --build
curl http://localhost:8000/health   # -> {"status": "ok"}
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
uvicorn backend.main:app --reload
pytest
```

## Project layout

```
backend/       FastAPI app: config, routers, app factory
database/      SQLAlchemy models, engine/session, Alembic migrations
tests/         unit / integration / agent test suites
```

Directories such as `agents/`, `tools/`, `rag/`, and `evaluation/` are introduced in the
phases that first populate them with real logic (see the Implementation Guide, Section 5)
rather than scaffolded empty ahead of time.

## Branching model

Trunk-based: `main` is always deployable. Work happens on short-lived
`feature/<slice-name>` branches merged into `main` via PR (Implementation Guide, Section 4).

## Tooling

| Concern | Tool |
|---|---|
| Dependency pinning | `pip-tools` (`requirements.in` / `requirements-dev.in` -> compiled `.txt`) |
| Lint & format | Ruff |
| Type checking | mypy (`--strict` on `database/models.py`; see `pyproject.toml`) |
| Tests | pytest |
| Pre-commit | Ruff + mypy + basic hygiene hooks |
| CI | GitHub Actions (`.github/workflows/ci.yml`) |
