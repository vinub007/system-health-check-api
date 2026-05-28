"""
System Health Check API - Main Application Entry Point
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.api.routes import router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.metrics import ACTIVE_REQUESTS, REQUEST_COUNT, REQUEST_LATENCY
from app.core.tracing import setup_tracing  # Fix issue 1: import the module

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "System Health Check API starting",
        extra={"event": "startup", "version": settings.APP_VERSION},
    )
    yield
    logger.info("System Health Check API shutting down", extra={"event": "shutdown"})


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Evaluates the health of a system composed of multiple, interdependent components arranged as a DAG.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start_time = time.time()

    ACTIVE_REQUESTS.inc()
    logger.info(
        "Incoming request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "client_ip": request.client.host if request.client else "unknown",
        },
    )

    try:
        response = await call_next(request)
        duration = time.time() - start_time
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code,
        ).inc()
        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=request.url.path,
        ).observe(duration)

        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        response.headers["X-Request-ID"] = request_id

        # Fix issue 3: propagate request_id into the active OTel span so logs
        # and traces can be correlated by a single ID without a full trace context.
        if settings.OTEL_ENABLED:
            from opentelemetry import trace as otel_trace
            span = otel_trace.get_current_span()
            if span.is_recording():
                span.set_attribute("http.request_id", request_id)

        return response
    except Exception as exc:
        duration = time.time() - start_time
        logger.error(
            "Request failed",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "duration_ms": round(duration * 1000, 2),
                "error": str(exc),
            },
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )
    finally:
        ACTIVE_REQUESTS.dec()


# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.include_router(router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness probe endpoint."""
    return {"status": "healthy", "version": settings.APP_VERSION}


@app.get("/ready", tags=["Health"])
async def readiness_check():
    """Readiness probe endpoint."""
    return {"status": "ready", "version": settings.APP_VERSION}


# Fix issues 1 & 2: call setup_tracing() first so the TracerProvider is
# registered before the instrumentor wraps the app. Gate both on OTEL_ENABLED
# so there is zero overhead when tracing is off.
setup_tracing()

if settings.OTEL_ENABLED:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)
    logger.info("FastAPI OTel instrumentation active")
