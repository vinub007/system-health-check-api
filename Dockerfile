# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps needed by matplotlib + gRPC (grpcio wheels need gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libfreetype6-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

# Issue 10 fix: declare ARG so the build-arg passed from CI is actually consumed.
# Falls back to 1.0.0 when built locally without --build-arg.
ARG APP_VERSION=1.0.0

# Environment defaults (overridable at runtime via docker run -e or compose)
ENV APP_NAME="System Health Check API" \
    APP_VERSION=${APP_VERSION} \
    ENVIRONMENT="production" \
    LOG_LEVEL="INFO" \
    LOG_FORMAT="json" \
    HEALTH_CHECK_TIMEOUT_SECONDS="10" \
    HEALTH_CHECK_MAX_CONCURRENCY="20" \
    OTEL_ENABLED="false" \
    OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317" \
    OTEL_SERVICE_NAME="system-health-api" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
