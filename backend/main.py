"""FastAPI application factory and router registration."""

from fastapi import FastAPI

from backend.api.routes_health import router as health_router
from backend.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(health_router)
    return app


app = create_app()
