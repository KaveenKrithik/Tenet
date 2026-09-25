"""
test_graph_builder.py — Stage 1 tests for parser, store, builder, and query.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from tenet.graph.builder import build_full_graph, update_graph
from tenet.graph.parser import Node, extract_edges, parse_file
from tenet.graph.query import find_node_by_name, get_scope_size, get_subgraph
from tenet.graph.store import GraphStore

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_A = str(FIXTURES_DIR / "sample_a.py")
SAMPLE_B = str(FIXTURES_DIR / "sample_b.py")
SAMPLE_C = str(FIXTURES_DIR / "sample_c.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path) -> GraphStore:
    """Return a fresh in-memory (tmp file) GraphStore for each test."""
    return GraphStore(str(tmp_path / "test_graph.sqlite"))


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParser:
    def test_parse_sample_a_finds_functions(self):
        nodes = parse_file(SAMPLE_A)
        names = {n.name for n in nodes}
        assert "add" in names
        assert "multiply" in names
        assert "compute" in names

    def test_parse_sample_a_finds_class(self):
        nodes = parse_file(SAMPLE_A)
        class_nodes = [n for n in nodes if n.type == "class"]
        assert any(n.name == "BaseProcessor" for n in class_nodes)

    def test_parse_sample_a_includes_module(self):
        nodes = parse_file(SAMPLE_A)
        module_nodes = [n for n in nodes if n.type == "module"]
        assert len(module_nodes) == 1

    def test_node_has_stable_id(self):
        """Same file + name should produce the same id across calls."""
        nodes1 = parse_file(SAMPLE_A)
        nodes2 = parse_file(SAMPLE_A)
        ids1 = {n.name: n.id for n in nodes1}
        ids2 = {n.name: n.id for n in nodes2}
        assert ids1 == ids2

    def test_node_line_numbers_are_positive(self):
        nodes = parse_file(SAMPLE_A)
        for n in nodes:
            assert n.line_start >= 1
            assert n.line_end >= n.line_start

    def test_content_hash_changes_when_content_changes(self, tmp_path):
        """Modifying a function should change its content_hash."""
        src = tmp_path / "mod.py"
        src.write_text("def foo(x):\n    return x\n")
        nodes_before = parse_file(str(src))
        foo_before = next(n for n in nodes_before if n.name == "foo")

        src.write_text("def foo(x, y):\n    return x + y\n")
        nodes_after = parse_file(str(src))
        foo_after = next(n for n in nodes_after if n.name == "foo")

        assert foo_before.content_hash != foo_after.content_hash

    def test_unsupported_extension_returns_empty(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello world")
        assert parse_file(str(f)) == []


class TestEdgeExtraction:
    def test_call_edge_between_functions(self):
        """compute() calls add() and multiply() — both edges must be detected."""
        nodes = parse_file(SAMPLE_A)
        edges = extract_edges(SAMPLE_A, nodes)
        edge_types = {(e.source_id, e.target_id, e.edge_type) for e in edges}
        node_by_name = {n.name: n for n in nodes}

        compute = node_by_name.get("compute")
        add = node_by_name.get("add")
        multiply = node_by_name.get("multiply")
        assert compute and add and multiply, "Required functions not parsed"

        assert any(
            src == compute.id and tgt == add.id and et == "calls"
            for src, tgt, et in edge_types
        ), "Expected compute→add calls edge"

        assert any(
            src == compute.id and tgt == multiply.id and et == "calls"
            for src, tgt, et in edge_types
        ), "Expected compute→multiply calls edge"

    def test_import_edges_detected(self):
        nodes = parse_file(SAMPLE_B)
        edges = extract_edges(SAMPLE_B, nodes)
        import_edges = [e for e in edges if e.edge_type == "imports"]
        assert len(import_edges) >= 1

    def test_no_self_edges(self):
        nodes = parse_file(SAMPLE_A)
        edges = extract_edges(SAMPLE_A, nodes)
        for e in edges:
            assert e.source_id != e.target_id, "Self-edge detected"


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------

class TestStore:
    def test_upsert_and_retrieve_nodes(self, tmp_db):
        nodes = parse_file(SAMPLE_A)
        tmp_db.upsert_nodes(nodes)
        stored = tmp_db.get_all_nodes()
        assert len(stored) == len(nodes)

    def test_upsert_is_idempotent(self, tmp_db):
        nodes = parse_file(SAMPLE_A)
        tmp_db.upsert_nodes(nodes)
        tmp_db.upsert_nodes(nodes)
        stored = tmp_db.get_all_nodes()
        assert len(stored) == len(nodes)  # no duplicates

    def test_delete_file_nodes(self, tmp_db):
        nodes_a = parse_file(SAMPLE_A)
        nodes_c = parse_file(SAMPLE_C)
        tmp_db.upsert_nodes(nodes_a)
        tmp_db.upsert_nodes(nodes_c)
        tmp_db.delete_file_nodes(SAMPLE_A)
        stored = tmp_db.get_all_nodes()
        for n in stored:
            assert n["file_path"] != SAMPLE_A

    def test_file_hash_round_trip(self, tmp_db):
        tmp_db.upsert_file_hash("/some/file.py", "abc123")
        assert tmp_db.get_file_hash("/some/file.py") == "abc123"
        assert tmp_db.get_file_hash("/nonexistent.py") is None


# ---------------------------------------------------------------------------
# Builder tests
# ---------------------------------------------------------------------------

class TestBuilder:
    def test_build_full_graph(self, tmp_db):
        build_full_graph(str(FIXTURES_DIR), tmp_db)
        nodes = tmp_db.get_all_nodes()
        file_paths = {n["file_path"] for n in nodes}
        # All three fixture files should have been parsed
        assert SAMPLE_A in file_paths
        assert SAMPLE_B in file_paths
        assert SAMPLE_C in file_paths

    def test_update_graph_only_touches_changed_file(self, tmp_path, tmp_db):
        """Modifying sample_c should not alter sample_a nodes."""
        # Copy fixtures to a temp dir so we can modify them safely
        fixtures_copy = tmp_path / "fixtures"
        shutil.copytree(str(FIXTURES_DIR), str(fixtures_copy))

        a_path = str(fixtures_copy / "sample_a.py")
        c_path = str(fixtures_copy / "sample_c.py")

        build_full_graph(str(fixtures_copy), tmp_db)

        # Snapshot sample_a node ids
        a_nodes_before = {
            n["id"]: n["content_hash"]
            for n in tmp_db.get_all_nodes()
            if n["file_path"] == a_path
        }

        # Modify sample_c
        original_c = Path(c_path).read_text()
        new_c = original_c.replace("def greet(name: str)", "def greet(name: str, suffix: str = '')")
        Path(c_path).write_text(new_c)
        update_graph([c_path], tmp_db)

        # sample_a nodes must be unchanged
        a_nodes_after = {
            n["id"]: n["content_hash"]
            for n in tmp_db.get_all_nodes()
            if n["file_path"] == a_path
        }
        assert a_nodes_before == a_nodes_after

    def test_update_graph_replaces_changed_nodes(self, tmp_path, tmp_db):
        """Modifying sample_a should update its nodes in the store."""
        fixtures_copy = tmp_path / "fixtures"
        shutil.copytree(str(FIXTURES_DIR), str(fixtures_copy))
        a_path = str(fixtures_copy / "sample_a.py")

        build_full_graph(str(fixtures_copy), tmp_db)

        add_before = next(
            n for n in tmp_db.get_all_nodes()
            if n["file_path"] == a_path and n["name"] == "add"
        )

        # Change the add function signature
        src = Path(a_path).read_text()
        src = src.replace("def add(x: int, y: int) -> int:", "def add(x: int, y: int, z: int = 0) -> int:")
        Path(a_path).write_text(src)
        update_graph([a_path], tmp_db)

        add_after = next(
            (n for n in tmp_db.get_all_nodes()
             if n["file_path"] == a_path and n["name"] == "add"),
            None,
        )
        assert add_after is not None
        assert add_before["content_hash"] != add_after["content_hash"]

    def test_update_graph_skips_unchanged_file(self, tmp_db):
        """Calling update_graph on an unchanged file should be a no-op."""
        nodes_before = parse_file(SAMPLE_A)
        tmp_db.upsert_nodes(nodes_before)
        # Record hash so it looks already ingested
        module_node = next(n for n in nodes_before if n.type == "module")
        tmp_db.upsert_file_hash(SAMPLE_A, module_node.content_hash)

        update_graph([SAMPLE_A], tmp_db)
        nodes_after = tmp_db.get_all_nodes()
        # Still the same number of nodes
        assert len(nodes_after) == len(nodes_before)


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------

class TestQuery:
    def test_get_subgraph_center_node_included(self, tmp_db):
        build_full_graph(str(FIXTURES_DIR), tmp_db)
        compute_node = find_node_by_name("compute", tmp_db)
        assert compute_node is not None
        sg = get_subgraph(compute_node["id"], hops=1, store=tmp_db)
        node_ids = {n["id"] for n in sg.nodes}
        assert compute_node["id"] in node_ids

    def test_get_subgraph_reaches_callees(self, tmp_db):
        build_full_graph(str(FIXTURES_DIR), tmp_db)
        compute_node = find_node_by_name("compute", tmp_db)
        add_node = find_node_by_name("add", tmp_db)
        assert compute_node and add_node
        sg = get_subgraph(compute_node["id"], hops=1, store=tmp_db)
        node_ids = {n["id"] for n in sg.nodes}
        assert add_node["id"] in node_ids

    def test_get_scope_size_returns_positive(self, tmp_db):
        build_full_graph(str(FIXTURES_DIR), tmp_db)
        compute_node = find_node_by_name("compute", tmp_db)
        assert compute_node
        node_count, edge_count = get_scope_size(compute_node["id"], hops=2, store=tmp_db)
        assert node_count > 0

    def test_get_subgraph_unknown_node(self, tmp_db):
        sg = get_subgraph("nonexistent_id", hops=2, store=tmp_db)
        assert sg.nodes == []
