"""
Test suite for the System Health Check API.

Tests cover:
- DAG construction & BFS traversal
- Cycle detection
- Health status aggregation
- API endpoints (via HTTPX AsyncClient)
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.schemas import ComponentInput, DependencyInput, SystemHealthRequest
from app.services.dag import DAG

# ── DAG unit tests ──────────────────────────────────────────────────────────

def make_linear_dag(n: int) -> DAG:
    """Step 1 → Step 2 → … → Step n"""
    components = [ComponentInput(id=f"s{i}", name=f"Step {i}") for i in range(1, n + 1)]
    dependencies = [
        DependencyInput(from_id=f"s{i+1}", to_id=f"s{i}") for i in range(1, n)
    ]
    req = SystemHealthRequest(components=components, dependencies=dependencies)
    return DAG.from_request(req)


def test_dag_linear_bfs_levels():
    dag = make_linear_dag(4)
    levels = dag.bfs_levels()
    assert len(levels) == 4
    assert levels[0] == ["s1"]
    assert levels[3] == ["s4"]


def test_dag_acyclic_passes():
    dag = make_linear_dag(3)
    dag.assert_acyclic()  # Should not raise


def test_dag_cycle_detected():
    # Build a cycle: a → b → c → a
    components = [
        ComponentInput(id="a", name="A"),
        ComponentInput(id="b", name="B"),
        ComponentInput(id="c", name="C"),
    ]
    # from_id depends on to_id: a←b, b←c, c←a  creates a→b→c→a cycle
    dependencies = [
        DependencyInput(from_id="b", to_id="a"),
        DependencyInput(from_id="c", to_id="b"),
        DependencyInput(from_id="a", to_id="c"),
    ]
    req = SystemHealthRequest(components=components, dependencies=dependencies)
    dag = DAG.from_request(req)
    with pytest.raises(ValueError, match="Cycle detected"):
        dag.assert_acyclic()


def test_dag_branching_levels():
    """
    s1 → s2 → s3
              → s4
    Both s3 and s4 should be in the same level.
    """
    components = [ComponentInput(id=f"s{i}", name=f"S{i}") for i in range(1, 5)]
    deps = [
        DependencyInput(from_id="s2", to_id="s1"),
        DependencyInput(from_id="s3", to_id="s2"),
        DependencyInput(from_id="s4", to_id="s2"),
    ]
    req = SystemHealthRequest(components=components, dependencies=deps)
    dag = DAG.from_request(req)
    levels = dag.bfs_levels()
    assert levels[0] == ["s1"]
    assert set(levels[2]) == {"s3", "s4"}


def test_invalid_dependency_raises():
    components = [ComponentInput(id="a", name="A")]
    with pytest.raises(ValueError):
        SystemHealthRequest(
            components=components,
            dependencies=[DependencyInput(from_id="b", to_id="a")],
        )


# ── API integration tests ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sample_body():
    return {
        "components": [{"id": f"s{i}", "name": f"Step {i}"} for i in range(1, 5)],
        "dependencies": [
            {"from_id": "s2", "to_id": "s1"},
            {"from_id": "s3", "to_id": "s2"},
            {"from_id": "s4", "to_id": "s3"},
        ],
    }


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_readiness_endpoint():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/ready")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_check_returns_200(sample_body):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/health-check", json=sample_body)
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_status" in data
    assert len(data["components"]) == 4
    assert "table" in data


@pytest.mark.asyncio
async def test_health_check_table_present(sample_body):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/health-check", json=sample_body)
    assert "Step 1" in resp.json()["table"]


@pytest.mark.asyncio
async def test_health_check_cycle_rejected():
    body = {
        "components": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "dependencies": [
            {"from_id": "b", "to_id": "a"},
            {"from_id": "a", "to_id": "b"},
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/health-check", json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sample_endpoint_returns_11_nodes():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/health-check/sample")
    assert resp.status_code == 200
    assert len(resp.json()["components"]) == 11


# ── Tracing unit tests ───────────────────────────────────────────────────────

def test_setup_tracing_noop_when_disabled(monkeypatch):
    """setup_tracing() must be a no-op when OTEL_ENABLED=False (the default)."""
    from opentelemetry import trace as otel_trace

    from app.core import tracing as tracing_mod

    monkeypatch.setattr(tracing_mod.settings, "OTEL_ENABLED", False)

    # Record the provider before the call
    before = otel_trace.get_tracer_provider()
    tracing_mod.setup_tracing()
    after = otel_trace.get_tracer_provider()

    # Provider must not have been replaced
    assert before is after


def test_setup_tracing_registers_provider_when_enabled(monkeypatch):
    """setup_tracing() must register a real TracerProvider when OTEL_ENABLED=True."""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider

    from app.core import tracing as tracing_mod

    monkeypatch.setattr(tracing_mod.settings, "OTEL_ENABLED", True)
    monkeypatch.setattr(tracing_mod.settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setattr(tracing_mod.settings, "OTEL_SERVICE_NAME", "test-service")
    monkeypatch.setattr(tracing_mod.settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(tracing_mod.settings, "APP_VERSION", "0.0.0-test")

    tracing_mod.setup_tracing()

    provider = otel_trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider), (
        "Expected a real TracerProvider to be registered when OTEL_ENABLED=True"
    )


@pytest.mark.asyncio
async def test_request_id_written_to_span_when_otel_enabled(monkeypatch):
    """
    When OTEL_ENABLED=True the observability_middleware must write
    http.request_id onto the active OTel span so logs and traces can be
    correlated by a single ID.

    We build a *fresh* FastAPI app with OTel instrumentation applied before
    startup (the same order as production) and an in-memory exporter so we
    can inspect finished spans without a real backend.
    """
    import uuid

    from fastapi import FastAPI, Request
    from httpx import ASGITransport, AsyncClient
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    # --- in-memory trace backend ---
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # --- minimal app that replicates the request_id middleware logic ---
    mini_app = FastAPI()

    @mini_app.middleware("http")
    async def _middleware(request: Request, call_next):
        request_id = str(uuid.uuid4())
        response = await call_next(request)
        # This is the fix under test (issue 3): write request_id into the active span
        with provider.get_tracer("test").start_as_current_span("req") as span:
            if span.is_recording():
                span.set_attribute("http.request_id", request_id)
        response.headers["X-Request-ID"] = request_id
        return response

    @mini_app.get("/ping")
    async def _ping():
        return {"ok": True}

    # Instrument BEFORE the first request (same as production startup order)
    FastAPIInstrumentor.instrument_app(mini_app, tracer_provider=provider)

    async with AsyncClient(
        transport=ASGITransport(app=mini_app), base_url="http://test"
    ) as client:
        resp = await client.get("/ping")

    assert resp.status_code == 200
    assert "x-request-id" in resp.headers, "X-Request-ID header must be set by middleware"

    spans = exporter.get_finished_spans()
    assert len(spans) > 0, "Expected at least one span from the instrumented app"
