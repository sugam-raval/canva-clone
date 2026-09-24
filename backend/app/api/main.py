"""FastAPI application — Lido.js (template) flow only."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.registry import describe as describe_adapters
from app.api.routes import lido
from app.config import get_settings
from app.db.session import dispose_engine, healthcheck
from app.lido_corpus.store import warm_catalog

log = structlog.get_logger(__name__)


def configure_logging(level: str) -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), 20))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), 20)),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    if not await healthcheck():
        log.error("db.unreachable", url=settings.database_url.split("@")[-1])

    # Load the embedding model and sync lidojs_templates/*.json into lido_templates now,
    # so the first request doesn't pay the ~15 s model load.
    started = time.monotonic()
    await warm_catalog()
    log.info("warmup.complete", seconds=round(time.monotonic() - started, 2),
             adapters=describe_adapters())
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Lido.js Template Designer",
        description="Prompt → best-matching Lido.js template, filled with copy and images.",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        duration = (time.monotonic() - started) * 1000
        log.info("http", method=request.method, path=request.url.path,
                 status=response.status_code, ms=round(duration, 1))
        response.headers["X-Response-Time-ms"] = f"{duration:.1f}"
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(lido.router)

    @app.get("/v1/health", tags=["health"])
    async def health() -> dict:
        return {
            "status": "ok",
            "database": await healthcheck(),
            "adapters": describe_adapters(),
            "openaiConfigured": get_settings().has_openai,
        }

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {"service": "lido-template-designer", "docs": "/docs", "health": "/v1/health"}

    return app


app = create_app()
