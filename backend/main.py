"""FastAPI application factory and router registration."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.api.routes_cards import router as cards_router
from backend.api.routes_health import router as health_router
from backend.api.routes_optimize import router as optimize_router
from backend.api.routes_recommend import router as recommend_router
from backend.api.routes_user import router as user_router
from backend.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(health_router)
    app.include_router(recommend_router)
    app.include_router(cards_router)
    app.include_router(user_router)
    app.include_router(optimize_router)

    # One consistent error envelope across every endpoint (Section 16), implemented once
    # here rather than repeated per-route.
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        body = (
            detail
            if isinstance(detail, dict) and "error" in detail
            else {"error": {"code": "http_error", "message": detail}}
        )
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": exc.errors()}},
        )

    return app


app = create_app()
