"""
paisa/backend/app/main.py
FastAPI application factory with full observability middleware stack.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.config import settings
from app.database import engine, Base
from app.api.v1 import auth, transactions, sms, budgets, analytics, sync
from app.middleware.logging import configure_structlog
from app.middleware.auth import AuthMiddleware

log = structlog.get_logger(__name__)

# ─── Prometheus metrics ────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "paisa_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "paisa_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
SMS_PROCESSED = Counter(
    "paisa_sms_processed_total",
    "SMS messages processed",
    ["status", "bank"],
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown lifecycle."""
    configure_structlog(json_logs=settings.JSON_LOGS)
    log.info("paisa.startup", version=settings.APP_VERSION, env=settings.ENV)

    # Verify DB connectivity on startup; fail fast rather than at first request
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # idempotent in dev

    log.info("paisa.db_connected")
    yield
    log.info("paisa.shutdown")
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Paisa Finance API",
        version=settings.APP_VERSION,
        docs_url="/docs" if settings.ENV != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request ID + latency middleware ───────────────────────────────
    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start = time.perf_counter()

        # Bind request context to all log calls in this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
        )

        try:
            response: Response = await call_next(request)
        except Exception as exc:
            log.exception("paisa.unhandled_error", exc_type=type(exc).__name__)
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "request_id": request_id},
            )

        elapsed = time.perf_counter() - start
        endpoint = request.url.path

        REQUEST_COUNT.labels(request.method, endpoint, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, endpoint).observe(elapsed)

        log.info(
            "paisa.request",
            status=response.status_code,
            duration_ms=round(elapsed * 1000, 2),
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(round(elapsed * 1000, 2))
        return response

    # ── Routers ───────────────────────────────────────────────────────
    API_PREFIX = "/api/v1"
    app.include_router(auth.router, prefix=f"{API_PREFIX}/auth", tags=["auth"])
    app.include_router(transactions.router, prefix=f"{API_PREFIX}/transactions", tags=["transactions"])
    app.include_router(sms.router, prefix=f"{API_PREFIX}/sms", tags=["sms"])
    app.include_router(budgets.router, prefix=f"{API_PREFIX}/budgets", tags=["budgets"])
    app.include_router(analytics.router, prefix=f"{API_PREFIX}/analytics", tags=["analytics"])
    app.include_router(sync.router, prefix=f"{API_PREFIX}/sync", tags=["sync"])

    # ── Health + metrics ───────────────────────────────────────────────
    @app.get("/healthz", include_in_schema=False)
    async def health():
        return {"status": "ok", "version": settings.APP_VERSION}

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ── OTel instrumentation ──────────────────────────────────────────
    if settings.OTEL_ENABLED:
        FastAPIInstrumentor.instrument_app(app)

    return app


app = create_app()
