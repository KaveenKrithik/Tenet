"""
query.py — graph query functions: get_subgraph, get_neighbors, get_scope_size.

Loads adjacency data from SQLite into a networkx DiGraph for BFS traversal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import networkx as nx

from tenet.graph.store import GraphStore

logger = logging.getLogger(__name__)


@dataclass
class Subgraph:
    """Result of a subgraph query."""
    center_node_id: str
    hops: int
    nodes: list[dict] = field(default_factory=list)   # raw node dicts from store
    edges: list[dict] = field(default_factory=list)   # raw edge dicts from store

    @property
    def node_ids(self) -> list[str]:
        return [n.get("id", "") for n in self.nodes if isinstance(n, dict) and n.get("id")]


def _build_nx_graph(store: GraphStore) -> nx.DiGraph:
    """Load all nodes and edges from the store into a networkx DiGraph."""
    G = nx.DiGraph()
    for node in store.get_all_nodes():
        G.add_node(node["id"], **node)
    edges = store.get_edges_for_nodes(list(G.nodes))
    for edge in edges:
        G.add_edge(edge["source_id"], edge["target_id"], edge_type=edge["edge_type"])
    return G


def get_subgraph(node_id: str, hops: int, store: GraphStore) -> Subgraph:
    """Return a Subgraph containing all nodes within ``hops`` of ``node_id``.

    Uses undirected BFS so we capture both callers and callees within the
    hop radius (direction matters for edges, but scope discovery should be
    bidirectional).
    """
    G = _build_nx_graph(store)
    if node_id not in G:
        logger.warning("get_subgraph: node %s not found in graph", node_id)
        return Subgraph(center_node_id=node_id, hops=hops)

    # BFS on undirected view to discover neighbours in all directions
    G_undirected = G.to_undirected()
    reachable = nx.single_source_shortest_path_length(G_undirected, node_id, cutoff=hops)
    reachable_ids = set(reachable.keys())

    nodes_in_scope = []
    for nid in reachable_ids:
        if nid in G.nodes:
            d = dict(G.nodes[nid])
            d.setdefault("id", nid)
            nodes_in_scope.append(d)

    edges_in_scope = [
        {"source_id": u, "target_id": v, "edge_type": data.get("edge_type", "")}
        for u, v, data in G.edges(data=True)
        if u in reachable_ids and v in reachable_ids
    ]

    return Subgraph(
        center_node_id=node_id,
        hops=hops,
        nodes=nodes_in_scope,
        edges=edges_in_scope,
    )


def get_neighbors(node_id: str, store: GraphStore) -> list[dict]:
    """Return immediate (1-hop) neighbours of a node, both in and out."""
    G = _build_nx_graph(store)
    if node_id not in G:
        return []
    neighbor_ids = set(G.predecessors(node_id)) | set(G.successors(node_id))
    return [dict(G.nodes[nid]) for nid in neighbor_ids if nid in G.nodes]


def get_scope_size(node_id: str, hops: int, store: GraphStore) -> tuple[int, int]:
    """Return (node_count, edge_count) for the subgraph within ``hops`` of ``node_id``.

    This is the lightweight probe used by the router to decide escalation tier
    without materialising the full context payload.
    """
    sg = get_subgraph(node_id, hops, store)
    return len(sg.nodes), len(sg.edges)


def find_node_by_name(name: str, store: GraphStore) -> dict | None:
    """Find the first node whose ``name`` field matches exactly."""
    all_nodes = store.get_all_nodes()
    for n in all_nodes:
        if n["name"] == name:
            return n
    return None


def find_nodes_for_files(file_paths: list[str], store: GraphStore) -> list[dict]:
    """Return all nodes belonging to the given file paths."""
    all_nodes = store.get_all_nodes()
    fp_set = set(file_paths)
    return [n for n in all_nodes if n["file_path"] in fp_set]
