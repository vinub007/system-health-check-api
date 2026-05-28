"""
DAG visualization using matplotlib + networkx.

Unhealthy / degraded components are highlighted in red / orange.
The image is returned as a base-64-encoded PNG string so the API
remains stateless (no file system writes required).

Tradeoffs
---------
* matplotlib + networkx add ~30 MB to the image.  We treat them as optional
  imports so the API degrades gracefully if they're absent.
* We use a hierarchical layout (BFS levels mapped to x-axis columns) rather
  than spring layout for clarity, since the DAG is typically shallow and wide.
"""
from __future__ import annotations

import base64
import io
import logging

from app.models.schemas import ComponentHealthResult, HealthStatus
from app.services.dag import DAG

logger = logging.getLogger(__name__)

STATUS_COLORS: dict[HealthStatus, str] = {
    HealthStatus.HEALTHY: "#4CAF50",    # green
    HealthStatus.DEGRADED: "#FF9800",   # orange
    HealthStatus.UNHEALTHY: "#F44336",  # red
    HealthStatus.UNKNOWN: "#9E9E9E",    # grey
}


def render_dag_image(
    dag: DAG,
    results: list[ComponentHealthResult],
) -> str | None:
    """Return base-64 PNG string or None if rendering is unavailable."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import networkx as nx
    except ImportError:
        logger.warning("matplotlib/networkx not installed – skipping DAG visualization")
        return None

    status_map: dict[str, HealthStatus] = {r.id: r.status for r in results}

    G = nx.DiGraph()
    for nid, node in dag.nodes.items():
        G.add_node(nid, label=node.name)
    for nid, node in dag.nodes.items():
        for child_id in node.children:
            G.add_edge(nid, child_id)

    # Build a hierarchical layout based on BFS levels
    try:
        levels = dag.bfs_levels()
    except Exception:
        levels = [[nid] for nid in dag.nodes]

    pos: dict[str, tuple] = {}
    for x, level_nodes in enumerate(levels):
        count = len(level_nodes)
        for y_idx, nid in enumerate(level_nodes):
            y = (count - 1) / 2 - y_idx  # centre the column
            pos[nid] = (x * 2.5, y * 1.8)

    node_colors = [
        STATUS_COLORS.get(status_map.get(nid, HealthStatus.UNKNOWN), "#9E9E9E")
        for nid in G.nodes
    ]
    labels = {nid: dag.nodes[nid].name for nid in G.nodes}

    fig, ax = plt.subplots(figsize=(max(8, len(levels) * 2.5), 6))
    ax.set_facecolor("#F8F9FA")
    fig.patch.set_facecolor("#F8F9FA")

    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edge_color="#555555",
        arrows=True,
        arrowsize=20,
        arrowstyle="-|>",
        connectionstyle="arc3,rad=0.05",
        min_source_margin=30,
        min_target_margin=30,
    )
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=node_colors,
        node_size=2200,
        node_shape="o",
        alpha=0.95,
    )
    nx.draw_networkx_labels(G, pos, labels=labels, ax=ax, font_size=8, font_color="white", font_weight="bold")

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=v, label=k.value.capitalize())
        for k, v in STATUS_COLORS.items()
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=8)
    ax.set_title("System Component DAG – Health Status", fontsize=12, pad=12)
    ax.axis("off")
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")
