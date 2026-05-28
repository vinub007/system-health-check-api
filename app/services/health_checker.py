"""
Async health-check evaluator.

Design decisions
----------------
* We use httpx (async) for real HTTP probes and asyncio.gather for parallelism
  within each BFS level.
* A semaphore caps total concurrent outbound requests to avoid overwhelming
  downstream systems.
* Components without a health_check_url receive a *simulated* check so the
  API remains fully functional in demo / unit-test environments.
* Each result captures response_time_ms so operators can spot latency regressions.
* We never raise inside a check – errors are caught and surfaced as UNHEALTHY
  so one flaky component doesn't crash the whole evaluation.

Tradeoffs
---------
* Simulation is deterministic-random seeded on component id for demo stability.
* Real checks do a simple HTTP GET and treat any 2xx as healthy.  More
  sophisticated checks (body inspection, gRPC, TCP) are out of scope.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.core.metrics import COMPONENT_CHECK_DURATION, COMPONENT_HEALTH_STATUS
from app.models.schemas import ComponentHealthResult, HealthStatus
from app.services.dag import DAG, DAGNode

logger = logging.getLogger(__name__)

# Semaphore is intentionally NOT created at module level.
# asyncio.Semaphore must be created inside a running event loop (Python 3.10+).
# A module-level Semaphore attaches to no loop on creation and raises
# "got Future attached to a different loop" when first awaited under uvicorn.
# Instead, _get_semaphore() lazily creates it on first use inside the event loop.
_sem: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Return the process-wide concurrency semaphore, creating it on first call."""
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(settings.HEALTH_CHECK_MAX_CONCURRENCY)
    return _sem


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _simulated_status(node: DAGNode) -> tuple[HealthStatus, float, int | None, str | None]:
    """
    Deterministic simulation based on node id hash so results are stable
    across repeated calls with the same input (useful for demos / tests).
    90 % of nodes are healthy; 7 % degraded; 3 % unhealthy.
    """
    seed = int(hashlib.sha256(node.id.encode()).hexdigest(), 16) % 1000
    rng = random.Random(seed)
    roll = rng.random()
    latency_ms = rng.uniform(5, 250)

    if roll < 0.03:
        return HealthStatus.UNHEALTHY, latency_ms, None, "Simulated: component unreachable"
    if roll < 0.10:
        return HealthStatus.DEGRADED, latency_ms, None, "Simulated: high latency detected"
    return HealthStatus.HEALTHY, latency_ms, None, None


async def _check_component(
    node: DAGNode,
    client: httpx.AsyncClient,
    timeout: float,
) -> ComponentHealthResult:
    """Evaluate health of a single component and return a result record."""
    start = time.perf_counter()

    try:
        async with _get_semaphore():
            if node.health_check_url:
                resp = await client.get(node.health_check_url, timeout=timeout)
                latency_ms = (time.perf_counter() - start) * 1000

                if 200 <= resp.status_code < 300:
                    status = HealthStatus.HEALTHY
                    error = None
                elif 500 <= resp.status_code < 600:
                    status = HealthStatus.UNHEALTHY
                    error = f"HTTP {resp.status_code}"
                else:
                    status = HealthStatus.DEGRADED
                    error = f"HTTP {resp.status_code}"

                status_code: int | None = resp.status_code
            else:
                # No URL → simulate
                status, latency_ms, status_code, error = _simulated_status(node)

    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - start) * 1000
        status = HealthStatus.UNHEALTHY
        status_code = None
        error = "Timeout"
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - start) * 1000
        status = HealthStatus.UNHEALTHY
        status_code = None
        error = str(exc)

    # Emit metrics
    COMPONENT_HEALTH_STATUS.labels(
        component_id=node.id,
        component_name=node.name,
    ).set(1 if status == HealthStatus.HEALTHY else 0)
    COMPONENT_CHECK_DURATION.labels(component_id=node.id).observe(latency_ms / 1000)

    logger.info(
        "Component checked",
        extra={
            "component_id": node.id,
            "component_name": node.name,
            "status": status.value,
            "response_time_ms": round(latency_ms, 2),
            "error": error,
        },
    )

    return ComponentHealthResult(
        id=node.id,
        name=node.name,
        status=status,
        response_time_ms=round(latency_ms, 2),
        status_code=status_code,
        error=error,
        checked_at=_now_iso(),
    )


async def evaluate_dag(dag: DAG, timeout: float | None = None) -> list[ComponentHealthResult]:
    """
    BFS-level parallel evaluation of all DAG nodes.

    Nodes in the same BFS level are checked concurrently; levels are processed
    sequentially so upstream results are available before downstream checks run
    (useful for future propagation logic without blocking overall throughput).
    """
    timeout = timeout or settings.HEALTH_CHECK_TIMEOUT_SECONDS
    levels = dag.bfs_levels()
    all_results: list[ComponentHealthResult] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for level_idx, level_nodes in enumerate(levels):
            logger.info(
                "Checking BFS level",
                extra={"level": level_idx, "nodes": level_nodes},
            )
            tasks = [
                _check_component(dag.nodes[nid], client, timeout)
                for nid in level_nodes
            ]
            level_results = await asyncio.gather(*tasks)
            all_results.extend(level_results)

    return all_results
