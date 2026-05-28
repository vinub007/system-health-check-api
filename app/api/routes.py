"""
API route definitions.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.metrics import (
    DAG_EDGE_COUNT,
    DAG_NODE_COUNT,
    HEALTH_CHECK_DURATION,
    HEALTH_CHECK_RUNS,
)
from app.models.schemas import (
    HealthStatus,
    SystemHealthRequest,
    SystemHealthResponse,
)
from app.services.dag import DAG
from app.services.health_checker import evaluate_dag
from app.services.visualizer import render_dag_image
from app.utils.table import format_results_table

router = APIRouter()
logger = logging.getLogger(__name__)


def _overall_status(summary: dict[str, int]) -> HealthStatus:
    if summary.get(HealthStatus.UNHEALTHY, 0) > 0:
        return HealthStatus.UNHEALTHY
    if summary.get(HealthStatus.DEGRADED, 0) > 0:
        return HealthStatus.DEGRADED
    if summary.get(HealthStatus.UNKNOWN, 0) > 0:
        return HealthStatus.UNKNOWN
    return HealthStatus.HEALTHY


@router.post(
    "/health-check",
    response_model=SystemHealthResponse,
    summary="Evaluate system health",
    description=(
        "Accept a DAG of system components, traverse it via BFS, "
        "asynchronously probe each component, and return an aggregated health report."
    ),
    tags=["Health Check"],
)
async def run_health_check(
    request: Request,
    body: SystemHealthRequest,
    visualize: bool = Query(False, description="Include base-64 DAG image in response"),
):
    request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info(
        "Health check requested",
        extra={
            "request_id": request_id,
            "component_count": len(body.components),
            "dependency_count": len(body.dependencies),
            "visualize": visualize,
        },
    )

    # Build & validate DAG
    try:
        dag = DAG.from_request(body)
        dag.assert_acyclic()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    DAG_NODE_COUNT.set(len(dag.nodes))
    DAG_EDGE_COUNT.set(dag.edge_count)

    # Evaluate
    HEALTH_CHECK_RUNS.inc()
    start = time.perf_counter()
    results = await evaluate_dag(dag)
    duration_ms = (time.perf_counter() - start) * 1000
    HEALTH_CHECK_DURATION.observe(duration_ms / 1000)

    # Aggregate
    status_counts: dict[str, int] = dict(
        Counter(r.status.value for r in results)
    )
    overall = _overall_status(
        {HealthStatus(k): v for k, v in status_counts.items()}
    )
    table = format_results_table(results)

    dag_image: str | None = None
    if visualize:
        dag_image = render_dag_image(dag, results)

    evaluated_at = datetime.now(UTC).isoformat()

    logger.info(
        "Health check complete",
        extra={
            "request_id": request_id,
            "overall_status": overall.value,
            "duration_ms": round(duration_ms, 2),
            "summary": status_counts,
        },
    )

    return SystemHealthResponse(
        request_id=request_id,
        overall_status=overall,
        evaluated_at=evaluated_at,
        duration_ms=round(duration_ms, 2),
        summary=status_counts,
        components=results,
        table=table,
        dag_image_base64=dag_image,
    )


@router.get(
    "/health-check/sample",
    summary="Get sample request body",
    tags=["Health Check"],
)
async def sample_request():
    """Return the sample 11-node DAG from the assignment brief."""
    return {
        "components": [
            {"id": f"step{i}", "name": f"Step {i}"} for i in range(1, 12)
        ],
        "dependencies": [
            {"from_id": "step2", "to_id": "step1"},
            {"from_id": "step3", "to_id": "step2"},
            {"from_id": "step4", "to_id": "step2"},
            {"from_id": "step5", "to_id": "step3"},
            {"from_id": "step7", "to_id": "step3"},
            {"from_id": "step6", "to_id": "step5"},
            {"from_id": "step8", "to_id": "step7"},
            {"from_id": "step9", "to_id": "step4"},
            {"from_id": "step10", "to_id": "step6"},
            {"from_id": "step10", "to_id": "step8"},
            {"from_id": "step10", "to_id": "step9"},
            {"from_id": "step11", "to_id": "step10"},
        ],
    }
