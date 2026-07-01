"""Liveness/readiness probe (API design doc, Section 13). No auth, no dependencies."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
