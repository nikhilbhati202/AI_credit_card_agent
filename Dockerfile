# Multi-stage build (implementation guide, Section 20.1): the runtime image
# never sees a compiler or the pip cache, only the resolved dependencies.

FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /install /usr/local
COPY backend/ backend/
COPY database/ database/
COPY tools/ tools/
COPY rag/ rag/
COPY services/ services/
COPY data/ data/
COPY evaluation/ evaluation/
COPY alembic.ini .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
