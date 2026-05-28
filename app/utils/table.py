"""
ASCII / Unicode table formatter for health check results.

We avoid tabulate as an extra dependency and roll a simple but readable
fixed-width table.  The table includes status emoji for quick scanning.
"""
from __future__ import annotations

from app.models.schemas import ComponentHealthResult, HealthStatus

STATUS_EMOJI = {
    HealthStatus.HEALTHY: "✅",
    HealthStatus.UNHEALTHY: "❌",
    HealthStatus.DEGRADED: "⚠️ ",
    HealthStatus.UNKNOWN: "❓",
}


def format_results_table(results: list[ComponentHealthResult]) -> str:
    headers = ["#", "ID", "Name", "Status", "RT (ms)", "HTTP", "Error"]
    rows = []
    for i, r in enumerate(results, 1):
        rows.append([
            str(i),
            r.id,
            r.name,
            f"{STATUS_EMOJI.get(r.status, '')} {r.status.value}",
            f"{r.response_time_ms:.1f}" if r.response_time_ms is not None else "-",
            str(r.status_code) if r.status_code else "-",
            (r.error or "")[:40],
        ])

    col_widths = [max(len(h), max((len(row[i]) for row in rows), default=0))
                  for i, h in enumerate(headers)]

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    fmt = "| " + " | ".join(f"{{:<{w}}}" for w in col_widths) + " |"

    lines = [
        sep,
        fmt.format(*headers),
        sep,
        *[fmt.format(*row) for row in rows],
        sep,
    ]
    return "\n".join(lines)
