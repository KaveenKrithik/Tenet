"""
test_ide_detector_and_cli.py — Unit tests for ide detection, store queries, and cli helpers.
"""
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from tenet.graph.builder import _should_ignore, update_graph
from tenet.graph.parser import Node
from tenet.graph.store import GraphStore
from tenet.ide_detector import detect_ide_and_plan
from tenet.triage.ollama_client import generate
from tenet.triage.prompt_optimizer import optimize_prompt
from pathlib import Path


def test_detect_ide_and_plan_default():
    result = detect_ide_and_plan()
    assert result.is_detected is True
    assert result.ide_name
    assert result.plan_name
    assert result.gemini_quota.remaining_pct >= 0
    assert result.claude_gpt_quota.name


def test_detect_ide_and_plan_override():
    override = {
        "ide_provider": "Cursor",
        "account_plan": "Cursor Pro",
    }
    result = detect_ide_and_plan(override)
    assert result.ide_name == "Cursor"
    assert result.plan_name == "Cursor Pro"


def test_get_nodes_by_file(tmp_path):
    db_file = str(tmp_path / "test_graph.sqlite")
    store = GraphStore(db_file)
    node1 = Node(
        id="n1",
        file_path="foo.py",
        name="func_a",
        type="function",
        line_start=1,
        line_end=5,
        content_hash="h1",
    )
    node2 = Node(
        id="n2",
        file_path="bar.py",
        name="func_b",
        type="function",
        line_start=1,
        line_end=5,
        content_hash="h2",
    )
    store.upsert_nodes([node1, node2])

    foo_nodes = store.get_nodes_by_file("foo.py")
    assert len(foo_nodes) == 1
    assert foo_nodes[0]["id"] == "n1"

    bar_nodes = store.get_nodes_by_file("bar.py")
    assert len(bar_nodes) == 1
    assert bar_nodes[0]["id"] == "n2"


def test_should_ignore():
    assert _should_ignore(Path(".venv/lib/python3.11/foo.py")) is True
    assert _should_ignore(Path("node_modules/package/index.js")) is True
    assert _should_ignore(Path(".git/objects/abc")) is True
    assert _should_ignore(Path("src/main.py")) is False


def test_update_graph_handles_deleted_file(tmp_path):
    db_file = str(tmp_path / "test_graph.sqlite")
    store = GraphStore(db_file)
    non_existent = str(tmp_path / "deleted.py")
    node = Node(
        id="d1",
        file_path=non_existent,
        name="ghost",
        type="function",
        line_start=1,
        line_end=5,
        content_hash="h_ghost",
    )
    store.upsert_nodes([node])
    assert len(store.get_nodes_by_file(non_existent)) == 1

    updated = update_graph([non_existent], store)
    assert non_existent in updated
    assert len(store.get_nodes_by_file(non_existent)) == 0


def test_ollama_client_object_response():
    @dataclass
    class FakeGenerateResponse:
        response: str

    fake_resp = FakeGenerateResponse(response="def hello(): pass")
    mock_client = MagicMock()
    mock_client.generate.return_value = fake_resp

    with patch("ollama.Client", return_value=mock_client):
        result = generate(prompt="write hello", context=MagicMock())
        assert result == "def hello(): pass"


def test_prompt_optimizer_object_response():
    @dataclass
    class FakeGenerateResponse:
        response: str

    fake_resp = FakeGenerateResponse(response="Refactored prompt")
    mock_client = MagicMock()
    mock_client.generate.return_value = fake_resp

    cfg = MagicMock()
    cfg.triage.ollama_host = "http://localhost:11434"
    cfg.triage.ollama_model = "qwen2.5-coder:7b"

    with patch("ollama.Client", return_value=mock_client):
        result = optimize_prompt(prompt="raw prompt", config=cfg)
        assert result == "Refactored prompt"
