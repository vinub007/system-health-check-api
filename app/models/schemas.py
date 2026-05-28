"""
Pydantic models for API request / response schemas.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


# ── Input models ────────────────────────────────────────────────────────────

class ComponentInput(BaseModel):
    """A single system component (node in the DAG)."""

    id: str = Field(..., description="Unique identifier for the component")
    name: str = Field(..., description="Human-readable component name")
    # Optional endpoint to probe; if omitted we simulate a health check
    health_check_url: str | None = Field(
        None,
        description="HTTP(S) URL to GET for the health check. "
                    "If omitted, a simulated check is performed.",
    )
    # Arbitrary key/value metadata (timeout overrides, tags, etc.)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DependencyInput(BaseModel):
    """A directed edge: `from_id` → `to_id` (from_id depends on to_id)."""

    from_id: str = Field(..., description="ID of the dependent component")
    to_id: str = Field(..., description="ID of the dependency component")


class SystemHealthRequest(BaseModel):
    """Top-level request body."""

    components: list[ComponentInput] = Field(
        ..., min_length=1, description="List of system components"
    )
    dependencies: list[DependencyInput] = Field(
        default_factory=list,
        description="Directed edges between components",
    )

    @model_validator(mode="after")
    def validate_dependency_ids(self) -> SystemHealthRequest:
        ids = {c.id for c in self.components}
        for dep in self.dependencies:
            if dep.from_id not in ids:
                raise ValueError(
                    f"Dependency from_id '{dep.from_id}' not found in components"
                )
            if dep.to_id not in ids:
                raise ValueError(
                    f"Dependency to_id '{dep.to_id}' not found in components"
                )
        return self


# ── Output models ───────────────────────────────────────────────────────────

class ComponentHealthResult(BaseModel):
    """Health result for a single component."""

    id: str
    name: str
    status: HealthStatus
    response_time_ms: float | None = None
    status_code: int | None = None
    error: str | None = None
    checked_at: str  # ISO-8601


class SystemHealthResponse(BaseModel):
    """Top-level API response."""

    request_id: str
    overall_status: HealthStatus
    evaluated_at: str  # ISO-8601
    duration_ms: float
    summary: dict[str, int] = Field(
        description="Count of components per status"
    )
    components: list[ComponentHealthResult]
    table: str = Field(description="Human-readable ASCII table")
    dag_image_base64: str | None = Field(
        None, description="Base-64-encoded PNG of the DAG (optional feature)"
    )
