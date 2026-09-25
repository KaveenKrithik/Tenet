"""
multi_agent.py — overlapping subgraph detection for concurrent agent tasks.

When multiple tasks are planned simultaneously, detecting overlapping code
scopes allows the pipeline to recommend task merging (to avoid redundant
context) or serialisation (to avoid write conflicts).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from tenet.graph.store import GraphStore
from tenet.graph.query import get_subgraph

logger = logging.getLogger(__name__)


@dataclass
class TaskScope:
    """Describes a single planned task's code scope."""
    task_id: str
    center_node_id: str
    hops: int


@dataclass
class OverlapGroup:
    """Two tasks whose subgraphs intersect."""
    task_a: TaskScope
    task_b: TaskScope
    shared_node_ids: list[str]
    overlap_ratio: float         # intersection / union of node IDs
    recommendation: str          # "merge" | "serialize"


def detect_overlaps(
    planned_tasks: list[TaskScope],
    store: GraphStore,
) -> list[OverlapGroup]:
    """Detect pairwise subgraph overlaps between planned tasks.

    For each pair of tasks:
    1. Retrieve their subgraphs from Stage 1.
    2. Compute intersection and union of node ID sets.
    3. If non-empty intersection → create an OverlapGroup.
       - ``overlap_ratio > 0.5`` → recommend "merge"
       - otherwise → recommend "serialize"

    Args:
        planned_tasks: List of TaskScope objects describing planned work.
        store: The graph store to query subgraphs from.

    Returns:
        List of OverlapGroup records (may be empty if no overlaps).
    """
    # Materialise subgraphs for each task
    subgraphs: dict[str, set[str]] = {}
    for task in planned_tasks:
        sg = get_subgraph(task.center_node_id, task.hops, store)
        subgraphs[task.task_id] = set(sg.node_ids)
        logger.debug(
            "detect_overlaps: task=%s has %d nodes in scope",
            task.task_id, len(subgraphs[task.task_id]),
        )

    groups: list[OverlapGroup] = []

    for i, task_a in enumerate(planned_tasks):
        for task_b in planned_tasks[i + 1:]:
            nodes_a = subgraphs[task_a.task_id]
            nodes_b = subgraphs[task_b.task_id]
            intersection = nodes_a & nodes_b

            if not intersection:
                continue  # disjoint, no overlap

            union = nodes_a | nodes_b
            ratio = len(intersection) / len(union) if union else 0.0
            recommendation = "merge" if ratio > 0.5 else "serialize"

            logger.info(
                "detect_overlaps: tasks %s + %s overlap %.1f%% → %s",
                task_a.task_id, task_b.task_id, ratio * 100, recommendation,
            )

            groups.append(OverlapGroup(
                task_a=task_a,
                task_b=task_b,
                shared_node_ids=list(intersection),
                overlap_ratio=ratio,
                recommendation=recommendation,
            ))

    return groups
