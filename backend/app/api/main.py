"""FastAPI application — IMPLEMENTATION_PLAN §0.10.

Consolidates the plan's `apps/api`, `apps/render`, `services/orchestrator` and
`services/ml-gateway` into one process (see docs/adr/0001-python-backend.md). The module
boundaries mirror the original service boundaries so they can be split out unchanged.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.registry import describe as describe_adapters
from app.adapters.registry import embedder
from app.api.routes import assets, docs, export, generate, lido
from app.config import get_settings
from app.db.session import dispose_engine, healthcheck
from app.jobs.progress import get_bus
from app.layout.fonts import get_registry

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

    # §6.8 warm pools: cold starts dominate p95. The sentence-transformer load alone is
    # ~18 s, which would blow the 3 s skeleton budget on the very first request.
    started = time.monotonic()
    get_registry()          # font catalog + metrics
    warm = getattr(embedder(), "warm", None)
    if warm is not None:
        warm()
    log.info("warmup.complete", seconds=round(time.monotonic() - started, 2),
             adapters=describe_adapters())

    if not await healthcheck():
        log.error("db.unreachable", url=settings.database_url.split("@")[-1])
    yield

    await get_bus().close()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Layered Design Generator",
        description="Prompt to fully editable multi-layer design (Part One).",
        version="0.1.0",
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
        if not request.url.path.startswith(("/v1/assets/raw", "/v1/fonts/")):
            log.info("http", method=request.method, path=request.url.path,
                     status=response.status_code, ms=round(duration, 1))
        response.headers["X-Response-Time-ms"] = f"{duration:.1f}"
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(generate.router)
    app.include_router(lido.router)
    app.include_router(docs.router)
    app.include_router(assets.router)
    app.include_router(export.router)

    @app.get("/v1/health", tags=["health"])
    async def health() -> dict:
        return {
            "status": "ok",
            "database": await healthcheck(),
            "adapters": describe_adapters(),
            "fonts": len(get_registry().families),
            "openaiConfigured": get_settings().has_openai,
        }

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {"service": "layered-design", "docs": "/docs", "health": "/v1/health"}

    return app


app = create_app()
