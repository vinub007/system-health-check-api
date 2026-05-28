"""
DAG construction, cycle detection, and BFS-level traversal.

Design decisions
----------------
* We use an adjacency-list representation (dict[str, list[str]]) rather than
  pulling in NetworkX so the core graph logic has zero extra dependencies.
* Cycle detection runs via DFS coloring before BFS so we fail fast with a
  clear error rather than looping forever.
* BFS produces a list of *levels* (nodes that can be checked in parallel)
  which the health-check service uses to schedule concurrent asyncio tasks.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

from app.models.schemas import SystemHealthRequest

logger = logging.getLogger(__name__)


@dataclass
class DAGNode:
    id: str
    name: str
    health_check_url: str | None
    metadata: dict
    children: list[str] = field(default_factory=list)   # edges FROM this node
    parents: list[str] = field(default_factory=list)    # edges TO this node


class DAG:
    """
    Directed Acyclic Graph of system components.

    Edges are stored as parent → child, meaning "child depends on parent".
    The sample image shows Step 1 → Step 2 → … which we interpret as
    data/control flowing left-to-right (Step 1 must be healthy for Step 2).
    """

    def __init__(self) -> None:
        self.nodes: dict[str, DAGNode] = {}

    # ── Construction ────────────────────────────────────────────────────────

    @classmethod
    def from_request(cls, request: SystemHealthRequest) -> DAG:
        dag = cls()
        for comp in request.components:
            dag.nodes[comp.id] = DAGNode(
                id=comp.id,
                name=comp.name,
                health_check_url=comp.health_check_url,
                metadata=comp.metadata,
            )

        for dep in request.dependencies:
            # dep.from_id depends on dep.to_id  →  edge: to_id → from_id
            dag.nodes[dep.to_id].children.append(dep.from_id)
            dag.nodes[dep.from_id].parents.append(dep.to_id)

        logger.info(
            "DAG constructed",
            extra={
                "node_count": len(dag.nodes),
                "edge_count": sum(len(n.children) for n in dag.nodes.values()),
            },
        )
        return dag

    # ── Validation ──────────────────────────────────────────────────────────

    def assert_acyclic(self) -> None:
        """Raise ValueError if a cycle is detected (DFS coloring)."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in self.nodes}

        def dfs(node_id: str) -> None:
            color[node_id] = GRAY
            for child_id in self.nodes[node_id].children:
                if color[child_id] == GRAY:
                    raise ValueError(
                        f"Cycle detected involving nodes '{node_id}' → '{child_id}'"
                    )
                if color[child_id] == WHITE:
                    dfs(child_id)
            color[node_id] = BLACK

        for nid in self.nodes:
            if color[nid] == WHITE:
                dfs(nid)

    # ── BFS traversal ───────────────────────────────────────────────────────

    def bfs_levels(self) -> list[list[str]]:
        """
        Return nodes grouped into BFS levels.
        Level 0 = root nodes (no parents), level N = nodes whose all parents
        are in levels 0..N-1.  Nodes within a level can be checked in parallel.
        """
        in_degree: dict[str, int] = {
            nid: len(node.parents) for nid, node in self.nodes.items()
        }
        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        levels: list[list[str]] = []
        visited: set[str] = set()

        while queue:
            level_size = len(queue)
            current_level: list[str] = []
            for _ in range(level_size):
                nid = queue.popleft()
                if nid in visited:
                    continue
                visited.add(nid)
                current_level.append(nid)
                for child_id in self.nodes[nid].children:
                    in_degree[child_id] -= 1
                    if in_degree[child_id] == 0:
                        queue.append(child_id)
            if current_level:
                levels.append(current_level)

        if len(visited) != len(self.nodes):
            unvisited = set(self.nodes) - visited
            raise ValueError(
                f"BFS did not reach all nodes – possible cycle or disconnected "
                f"graph. Unreached nodes: {unvisited}"
            )

        logger.info(
            "BFS traversal complete",
            extra={"levels": len(levels), "total_nodes": len(visited)},
        )
        return levels

    # ── Helpers ─────────────────────────────────────────────────────────────

    @property
    def edge_count(self) -> int:
        return sum(len(n.children) for n in self.nodes.values())
