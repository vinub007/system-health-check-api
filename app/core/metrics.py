"""
Prometheus metrics for the System Health Check API.
Exposed at /metrics for scraping by Prometheus / Grafana.
"""
from prometheus_client import Counter, Gauge, Histogram

# ── HTTP layer ──────────────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

ACTIVE_REQUESTS = Gauge(
    "http_active_requests",
    "Number of HTTP requests currently being processed",
)

# ── Health-check evaluation layer ───────────────────────────────────────────
HEALTH_CHECK_RUNS = Counter(
    "health_check_runs_total",
    "Total number of system health-check evaluations",
)

HEALTH_CHECK_DURATION = Histogram(
    "health_check_duration_seconds",
    "End-to-end duration of a full health-check evaluation",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

COMPONENT_HEALTH_STATUS = Gauge(
    "component_health_status",
    "Current health status of a component (1=healthy, 0=unhealthy)",
    ["component_id", "component_name"],
)

COMPONENT_CHECK_DURATION = Histogram(
    "component_check_duration_seconds",
    "Duration of an individual component health check",
    ["component_id"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

DAG_NODE_COUNT = Gauge(
    "dag_node_count",
    "Number of nodes in the last evaluated DAG",
)

DAG_EDGE_COUNT = Gauge(
    "dag_edge_count",
    "Number of edges in the last evaluated DAG",
)
