"""Structured (JSON) request logging (guide Section 19) - closes a gap from Phase 1, where
no LLM calls existed yet to make tracing meaningful. Phase 2 introduces the first two
LLM-touching nodes, so this is the natural point to wire it in, not a deferred nice-to-have.

Two destinations per Section 19: a JSON log line (operational debugging) and a
recommendation_logs DB row (product/audit trail, FR-11) - written by the caller via
log_recommendation(), which does both in one call.
"""

import contextlib
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from database.models import RecommendationLog

logger = logging.getLogger("credit_card_agent")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


@contextmanager
def timed_request() -> Iterator[dict[str, Any]]:
    """Yields a dict that the caller fills in; latency_ms is computed automatically."""
    start = time.perf_counter()
    payload: dict[str, Any] = {}
    try:
        yield payload
    finally:
        payload["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)


def log_recommendation(
    db: Session,
    *,
    user_id: str | None,
    query: str,
    intent: str | None,
    retrieved_chunk_ids: list[int],
    final_answer: dict[str, Any] | None,
    latency_ms: float,
    confidence: str | None = None,
) -> None:
    """Write one structured JSON log line + one recommendation_logs row (Section 19/FR-11).

    Never raises - a logging failure must not fail the user-facing request.
    """
    record = {
        "event": "recommendation",
        "user_id": user_id,
        "query": query,
        "intent": intent,
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "latency_ms": latency_ms,
        "confidence": confidence,
    }
    with contextlib.suppress(Exception):  # logging must never break the request
        logger.info(json.dumps(record))

    try:
        db.add(
            RecommendationLog(
                user_id=user_id,
                query=query,
                intent=intent,
                retrieved_chunk_ids=retrieved_chunk_ids,
                final_answer=final_answer,
                confidence=confidence,
                latency_ms=int(latency_ms),
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 - must not fail the request, but never swallow silently
        db.rollback()
        logger.error(
            json.dumps(
                {
                    "event": "recommendation_log_write_failed",
                    "user_id": user_id,
                    "query": query,
                    "intent": intent,
                },
                default=str,
            ),
            exc_info=True,
        )
