# Project Run Guide

Every command needed to set up, run, test, and operate this project, in the order you'd
actually use them. For narrative explanations see `README.md`; for architecture see
`docs/ARCHITECTURE.md`; for the free-LLM setup see `docs/COLAB_SETUP.md`.

## 1. Prerequisites

- Docker Desktop (or another Docker Engine + Compose v2)
- `git`
- A working LLM endpoint - a free Google Colab notebook (see `docs/COLAB_SETUP.md`), no
  payment or account beyond a Google login required

## 2. One-time setup

```bash
git clone <this-repo-url> && cd AI_credit_card_agent
cp .env.example .env
```

Then get an LLM endpoint reachable and put its URL in `.env`:

```bash
# Follow docs/COLAB_SETUP.md end-to-end in the Colab notebook, then paste the resulting
# https://<random-words>.trycloudflare.com/v1 URL into .env's LLM_BASE_URL.
```

## 3. Start the full stack (Docker - recommended path)

```bash
docker compose up -d --build
```

Brings up 3 containers:
- `db` - Postgres 16 + pgvector, port 5432
- `app` - FastAPI backend, port 8000 (runs `alembic upgrade head` automatically on start)
- `ui` - Streamlit chat UI, port 8501

Check it's healthy:

```bash
curl http://localhost:8000/health
# -> {"status":"ok"}
```

Seed the database (5 real cards + transfer partners; only needed once, or after a full reset):

```bash
docker compose exec app python -m database.seed
```

Confirm the seed worked:

```bash
curl http://localhost:8000/api/v1/cards
```

## 4. Open the frontend

```
http://localhost:8501
```

That's the entire UI - a chat box. List your owned cards in the sidebar, type a query, get a
recommendation. See `README.md` for example queries.

## 5. Talk to the API directly (curl)

```bash
# Single-transaction recommendation
curl -X POST http://localhost:8000/api/v1/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "I am spending Rs. 50,000 on flights.", "cards_owned": ["Axis Atlas", "Axis ACE"]}'

# Monthly optimization (needs >= 3 owned cards)
curl -X POST http://localhost:8000/api/v1/optimize/monthly \
  -H "Content-Type: application/json" \
  -d '{"query": "Monthly: 50000 on flights, 4000 on utility bills, 20000 online shopping", "cards_owned": ["Axis Atlas", "Axis ACE", "SBI Cashback"]}'

# Transfer evaluation -> pending approval
curl -X POST http://localhost:8000/api/v1/transfer/evaluate \
  -H "Content-Type: application/json" \
  -d '{"query": "Should I transfer 10000 miles to Singapore Airlines KrisFlyer?", "cards_owned": ["Axis Atlas"]}'
# -> {"status": "pending_approval", "session_id": "...", "proposal": {...}}

# Confirm (or cancel) that transfer - use the session_id from the previous response
curl -X POST http://localhost:8000/api/v1/transfer/confirm \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<session_id from above>", "approved": true}'

# List seeded cards
curl http://localhost:8000/api/v1/cards

# User profile (create/read)
curl -X PUT http://localhost:8000/api/v1/user/profile \
  -H "Content-Type: application/json" \
  -d '{"user_id": "demo-user", "cards_owned": ["Axis Atlas", "Axis ACE"]}'
curl "http://localhost:8000/api/v1/user/profile?user_id=demo-user"
```

## 6. Updating the Colab tunnel URL (it changes every notebook restart)

```bash
# 1. Re-run the Colab cells; copy the new https://<...>.trycloudflare.com URL.
# 2. Edit .env's LLM_BASE_URL to the new URL.
# 3. Recreate the app container - a plain `restart` does NOT reload .env, you must force-recreate:
docker compose up -d --force-recreate app

# Verify the container actually picked up the new URL:
docker compose exec app printenv LLM_BASE_URL
```

## 7. Stopping / tearing down

```bash
docker compose stop            # stop containers, keep data (pgdata volume persists)
docker compose down            # stop + remove containers, keep the pgdata volume
docker compose down -v         # stop + remove containers AND the pgdata volume (full reset)
```

## 8. Local development (without Docker)

```bash
python -m venv .venv
.venv/Scripts/activate            # .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
pre-commit install

# Point .env at a reachable Postgres instance and configure LLM_BASE_URL (see section 2), then:
alembic upgrade head
python -m database.seed
uvicorn backend.main:app --reload

# In a second terminal:
API_BASE_URL=http://localhost:8000/api/v1 streamlit run app/streamlit_app.py
```

## 9. Tests

```bash
pytest                          # everything (124 tests: unit, integration, agent, ui)
pytest tests/unit -q            # just unit tests (pure logic, no DB/LLM)
pytest tests/integration -q     # real HTTP + real DB, LLM mocked
pytest tests/agent -q           # compiled LangGraph graph invoked directly
pytest tests/ui -q              # Streamlit app driven headlessly via AppTest
pytest --cov --cov-report=term-missing   # with coverage report
```

No live LLM or paid API key is needed for any of these - the two LLM-touching nodes are
mocked in `tests/conftest.py`.

## 10. Evaluation harness (golden-set gates, also LLM-free)

```bash
python -m evaluation.calculation_eval            # must be 100%
python -m evaluation.monthly_optimization_eval   # must be 100%
python -m evaluation.rag_eval                    # must be >= 0.75
python -m evaluation.hallucination_eval          # must be 0% ungrounded
```

## 11. Linting / formatting / type-checking

```bash
ruff check .                    # lint
ruff check . --fix              # lint, auto-fixing what it can
ruff format .                   # format
ruff format --check .           # format, check-only (what CI runs)
mypy database/models.py tools/calculator.py tools/retriever.py tools/transfer_calculator.py agents/ backend/ services/ monitoring/ app/streamlit_app.py
```

## 12. Database migrations (Alembic)

```bash
alembic upgrade head             # apply all migrations
alembic downgrade -1              # roll back one revision
alembic revision --autogenerate -m "describe the change"   # create a new migration
alembic current                   # show current revision
```

## 13. Dependency changes (pip-tools)

If you edit `requirements.in`, `requirements-app.in`, or `requirements-dev.in`, recompile the
corresponding `.txt`:

```bash
.venv/Scripts/python -m piptools compile requirements.in -o requirements.txt
.venv/Scripts/python -m piptools compile requirements-app.in -o requirements-app.txt
.venv/Scripts/python -m piptools compile requirements-dev.in -o requirements-dev.txt
```

## 14. Rollback (Docker image tag)

```bash
# Build and deploy a specific commit:
APP_IMAGE_TAG=$(git rev-parse --short HEAD) docker compose build app
APP_IMAGE_TAG=$(git rev-parse --short HEAD) docker compose up -d app

# Roll back to a previously-built tag - no rebuild needed, the image is already local:
APP_IMAGE_TAG=<previous-sha> docker compose up -d app
```

## 15. Troubleshooting quick checks

```bash
docker compose ps                                  # container status
docker compose logs app --tail 50                   # recent backend logs
docker compose logs app -f                          # follow backend logs live
curl http://localhost:8000/health                   # is the backend up?
curl https://<your-tunnel>.trycloudflare.com/v1/models   # is the Colab tunnel up?
docker compose exec app printenv LLM_BASE_URL        # what URL is the container actually using?
```

See `docs/COLAB_SETUP.md`'s troubleshooting table for Colab/tunnel-specific issues
(403 errors, connection timeouts, low-confidence classification, etc.).

### `curl http://localhost:8000/health` fails with "Failed to connect" / "Could not connect to server"

Means the `app` container isn't running at all. Check what's actually happening:

```bash
docker compose ps -a                    # is app "Exited"? what exit code?
docker compose logs app --tail 50       # the actual error
```

Two causes seen in practice:

1. **`app` exits with `sqlalchemy.exc.OperationalError: ... failed to resolve host 'db'`** - the
   `db` container has been disconnected from the Docker network (can happen after a Docker
   Desktop restart). Fix by recreating the whole stack (safe - your data survives in the
   `pgdata` named volume, independent of the containers):
   ```bash
   docker compose down       # removes containers only, NOT the pgdata volume
   docker compose up -d
   ```

2. **`docker compose up` itself fails with `Bind for 0.0.0.0:5432 failed: port is already
   allocated`** - another Postgres (yours or a different project's) already has port 5432 on
   this machine. Check what's using it:
   ```bash
   docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep 5432
   ```
   Don't stop someone else's unrelated container - instead remap this project's host-side
   port in `docker-compose.yml`'s `db` service (the `app` container still reaches `db` on the
   unchanged internal port 5432 over the Docker network, so nothing else needs to change):
   ```yaml
   ports:
     - "5433:5432"   # was "5432:5432"
   ```
   This repo's `docker-compose.yml` is already set to `5433:5432` for this reason. If you ever
   want to connect a local `psql`/GUI client directly to this project's Postgres from the host
   machine, connect to port `5433`, not `5432`.
