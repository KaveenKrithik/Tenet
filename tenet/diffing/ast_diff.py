"""
ast_diff.py — structural AST-level diff between two versions of a file.

Instead of line-level diffing, we compare parsed node trees so we can
report *which* functions/classes changed and *how* (signature vs body).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from tenet.graph.parser import Node, _get_parser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Change:
    """Describes a single structural change at the node level."""
    node_id: str
    node_name: str
    change_type: str   # signature_changed | body_changed | added | removed
    summary: str       # human-readable description, e.g. "foo(x) → foo(x, y)"
    old_signature: Optional[str] = None
    new_signature: Optional[str] = None


@dataclass
class ContextPayload:
    """Compressed context assembled for a prompt: scope + diffs instead of full sources."""
    scope_node_ids: list[str] = field(default_factory=list)
    # Map node_id → compressed text (diff summary OR full source if no prior version)
    node_contexts: dict[str, str] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)
    estimated_tokens: int = 0


# ---------------------------------------------------------------------------
# Signature extraction helpers
# ---------------------------------------------------------------------------

def _extract_python_signature(source_bytes: bytes, node) -> str:
    """Extract the function/class signature line from a tree-sitter node."""
    text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    lines = text.splitlines()

    # For functions: signature = everything up to and including the first ':'
    if node.type in ("function_definition", "async_function_definition"):
        sig_lines = []
        for line in lines:
            sig_lines.append(line)
            stripped = line.rstrip()
            if stripped.endswith(":") and len(sig_lines) > 0:
                break
        return " ".join(l.strip() for l in sig_lines)

    # For classes: first line is the signature
    return lines[0].strip() if lines else ""


def _extract_python_body_hash(source_bytes: bytes, node) -> str:
    """Return a content hash of just the body of a function/class (excluding signature)."""
    text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    lines = text.splitlines()

    # Skip the first line(s) that form the signature
    body_lines = lines[1:]  # simplification: first line is always the def/class line
    body_text = "\n".join(body_lines)
    return Node.make_content_hash(body_text)


# ---------------------------------------------------------------------------
# Core diff implementation
# ---------------------------------------------------------------------------

def _parse_named_nodes(content: str, language: str) -> dict[str, dict]:
    """Parse content and return {qualified_name: {node_info}} for all named nodes."""
    source_bytes = content.encode("utf-8")
    try:
        parser = _get_parser(language)
        tree = parser.parse(source_bytes)
        root = tree.root_node

        result: dict[str, dict] = {}

        def walk(node, class_name: Optional[str] = None):
            if node.type in ("function_definition", "async_function_definition"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    raw_name = source_bytes[name_node.start_byte:name_node.end_byte].decode()
                    qualified = f"{class_name}.{raw_name}" if class_name else raw_name
                    sig = _extract_python_signature(source_bytes, node)
                    body_hash = _extract_python_body_hash(source_bytes, node)
                    full_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
                    result[qualified] = {
                        "signature": sig,
                        "body_hash": body_hash,
                        "full_text": full_text,
                        "type": "method" if class_name else "function",
                    }
                    for child in node.children:
                        walk(child, class_name)
            elif node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    cls_name = source_bytes[name_node.start_byte:name_node.end_byte].decode()
                    sig = _extract_python_signature(source_bytes, node)
                    body_hash = _extract_python_body_hash(source_bytes, node)
                    full_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
                    result[cls_name] = {
                        "signature": sig,
                        "body_hash": body_hash,
                        "full_text": full_text,
                        "type": "class",
                    }
                    for child in node.children:
                        walk(child, cls_name)
            else:
                for child in node.children:
                    walk(child, class_name)

        walk(root)
        return result
    except Exception as exc:
        logger.warning("_parse_named_nodes: parse failed: %s", exc)
        return {}



def structural_diff(old_content: str, new_content: str, language: str = "python") -> list[Change]:
    """Compute a structural AST diff between two source code versions.

    Returns a list of ``Change`` records at the function/class granularity.
    Changes are classified as:
    - ``added``: node present in new but not old
    - ``removed``: node present in old but not new
    - ``signature_changed``: function/class header changed (params, return type)
    - ``body_changed``: only the function body changed, signature intact
    """
    changes: list[Change] = []

    try:
        old_nodes = _parse_named_nodes(old_content, language)
        new_nodes = _parse_named_nodes(new_content, language)
    except Exception as exc:
        logger.warning("structural_diff: parse failed: %s", exc)
        return changes

    old_names = set(old_nodes.keys())
    new_names = set(new_nodes.keys())

    # Added nodes
    for name in new_names - old_names:
        info = new_nodes[name]
        node_id = Node.make_id(f"<diff>:{name}", name)
        changes.append(Change(
            node_id=node_id,
            node_name=name,
            change_type="added",
            summary=f"[added] {info['signature']}",
            new_signature=info["signature"],
        ))

    # Removed nodes
    for name in old_names - new_names:
        info = old_nodes[name]
        node_id = Node.make_id(f"<diff>:{name}", name)
        changes.append(Change(
            node_id=node_id,
            node_name=name,
            change_type="removed",
            summary=f"[removed] {info['signature']}",
            old_signature=info["signature"],
        ))

    # Modified nodes (signature vs body)
    for name in old_names & new_names:
        old_info = old_nodes[name]
        new_info = new_nodes[name]
        node_id = Node.make_id(f"<diff>:{name}", name)

        sig_changed = old_info["signature"] != new_info["signature"]
        body_changed = old_info["body_hash"] != new_info["body_hash"]

        if sig_changed:
            changes.append(Change(
                node_id=node_id,
                node_name=name,
                change_type="signature_changed",
                summary=f"{old_info['signature']} → {new_info['signature']}",
                old_signature=old_info["signature"],
                new_signature=new_info["signature"],
            ))
        elif body_changed:
            changes.append(Change(
                node_id=node_id,
                node_name=name,
                change_type="body_changed",
                summary=f"[body changed] {new_info['signature']}",
                old_signature=old_info["signature"],
                new_signature=new_info["signature"],
            ))

    return changes


def compress_context(
    node_id: str,
    hops: int,
    changes: list[Change],
    store,  # GraphStore — imported at call site to avoid circular imports
) -> ContextPayload:
    """Build a compressed ContextPayload for the given scope.

    For nodes that appear in ``changes``, we include the diff summary rather
    than the full source. For nodes with no prior version, we include the full
    source. This minimises tokens while preserving all semantically relevant
    context.
    """
    from tenet.graph.query import get_subgraph
    from pathlib import Path

    sg = get_subgraph(node_id, hops, store)
    change_by_name = {c.node_name: c for c in changes}

    node_contexts: dict[str, str] = {}

    for node_dict in sg.nodes:
        name = node_dict.get("name", "")
        file_path = node_dict.get("file_path", "")
        nid = node_dict.get("id", "")

        if name in change_by_name:
            # Use the compressed diff summary
            c = change_by_name[name]
            node_contexts[nid] = f"[DIFF] {c.summary}"
        else:
            # Include full source for context
            try:
                src = Path(file_path).read_text(errors="replace") if file_path else ""
                # Truncate to the relevant lines
                line_start = node_dict.get("line_start", 1) - 1
                line_end = node_dict.get("line_end", 0)
                lines = src.splitlines()
                snippet = "\n".join(lines[line_start:line_end]) if lines else src
                node_contexts[nid] = snippet
            except OSError:
                node_contexts[nid] = f"[source unavailable: {file_path}]"

    # Rough token estimate: 1 token ≈ 4 chars
    total_chars = sum(len(v) for v in node_contexts.values())
    estimated_tokens = total_chars // 4

    return ContextPayload(
        scope_node_ids=sg.node_ids,
        node_contexts=node_contexts,
        changes=changes,
        estimated_tokens=estimated_tokens,
    )
