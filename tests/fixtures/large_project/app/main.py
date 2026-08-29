"""Application factory and middleware."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.routes import users, items
from app.services.auth import AuthMiddleware


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="LargeTest", docs_url=None, redoc_url=None)
    app.include_router(users.router, prefix="/api/users")
    app.include_router(items.router, prefix="/api/items")
    app.add_middleware(AuthMiddleware)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
