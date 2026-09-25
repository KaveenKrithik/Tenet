"""
parser.py — tree-sitter-based AST parsing for Python, JavaScript, TypeScript.

Extracts `Node` and `Edge` records that feed the knowledge graph.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """A code entity (function, class, method, module) extracted from source."""
    id: str                  # sha256(file_path + ":" + qualified_name)
    type: str                # function | class | method | module
    name: str
    file_path: str
    line_start: int
    line_end: int
    content_hash: str        # sha256 of the node's source text

    @staticmethod
    def make_id(file_path: str, qualified_name: str) -> str:
        raw = f"{file_path}:{qualified_name}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def make_content_hash(source: str) -> str:
        return hashlib.sha256(source.encode()).hexdigest()[:16]


@dataclass
class Edge:
    """A directed relationship between two code nodes."""
    source_id: str
    target_id: str
    edge_type: str           # calls | imports | inherits | depends_on


# ---------------------------------------------------------------------------
# Language → tree-sitter grammar mapping
# ---------------------------------------------------------------------------

_LANG_GRAMMAR_MAP = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "tsx": "tsx",
}

_EXT_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "tsx",
    ".ts": "typescript",
    ".tsx": "tsx",
}


def _get_language(lang_name: str):
    """Return a tree-sitter Language object for the given language name."""
    try:
        import tree_sitter_languages as tsl
        return tsl.get_language(lang_name)
    except Exception as exc:
        raise RuntimeError(f"Cannot load tree-sitter grammar for '{lang_name}': {exc}") from exc


def _get_parser(lang_name: str):
    """Return a configured tree-sitter Parser for the given language."""
    try:
        from tree_sitter import Parser
        parser = Parser()
        parser.set_language(_get_language(lang_name))
        return parser
    except Exception as exc:
        raise RuntimeError(f"Cannot create tree-sitter parser for '{lang_name}': {exc}") from exc


def detect_language(file_path: str) -> Optional[str]:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    return _EXT_TO_LANG.get(ext)


# ---------------------------------------------------------------------------
# AST traversal helpers
# ---------------------------------------------------------------------------

def _text(node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _node_name(node, source_bytes: bytes) -> Optional[str]:
    """Extract the identifier name from a declaration node."""
    for child in node.children:
        if child.type == "identifier":
            return _text(child, source_bytes)
    return None


# ---------------------------------------------------------------------------
# Python extractor
# ---------------------------------------------------------------------------

def _extract_python_nodes(tree_root, source_bytes: bytes, file_path: str) -> list[Node]:
    nodes: list[Node] = []
    source_str = source_bytes.decode("utf-8", errors="replace")

    # Top-level module node
    module_id = Node.make_id(file_path, "<module>")
    module_hash = Node.make_content_hash(source_str)
    module_name = Path(file_path).name or "<module>"
    nodes.append(Node(
        id=module_id, type="module", name=module_name,
        file_path=file_path,
        line_start=1, line_end=source_str.count("\n") + 1,
        content_hash=module_hash,
    ))

    def walk(node, class_name: Optional[str] = None):
        if node.type in ("function_definition", "async_function_definition"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, source_bytes)
                qualified = f"{class_name}.{name}" if class_name else name
                node_text = _text(node, source_bytes)
                gw_node = Node(
                    id=Node.make_id(file_path, qualified),
                    type="method" if class_name else "function",
                    name=qualified,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    content_hash=Node.make_content_hash(node_text),
                )
                nodes.append(gw_node)
                for child in node.children:
                    walk(child, class_name)

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                cls_name = _text(name_node, source_bytes)
                cls_text = _text(node, source_bytes)
                gw_node = Node(
                    id=Node.make_id(file_path, cls_name),
                    type="class",
                    name=cls_name,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    content_hash=Node.make_content_hash(cls_text),
                )
                nodes.append(gw_node)
                for child in node.children:
                    walk(child, cls_name)
        else:
            for child in node.children:
                walk(child, class_name)

    walk(tree_root)
    return nodes


# ---------------------------------------------------------------------------
# Python edge extractor
# ---------------------------------------------------------------------------

def _extract_python_edges(tree_root, source_bytes: bytes, file_path: str, nodes: list[Node]) -> list[Edge]:
    edges: list[Edge] = []
    node_by_name: dict[str, Node] = {n.name: n for n in nodes}
    module_node = next((n for n in nodes if n.type == "module"), None)

    def walk_calls(node, current_func: Optional[Node]):
        if node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee_name = _text(func_node, source_bytes).split("(")[0].strip()
                # Look for a matching node
                target = node_by_name.get(callee_name)
                if target and current_func and current_func.id != target.id:
                    edges.append(Edge(
                        source_id=current_func.id,
                        target_id=target.id,
                        edge_type="calls",
                    ))
        for child in node.children:
            walk_calls(child, current_func)

    def walk_imports(node):
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    name = _text(child, source_bytes)
                    if module_node:
                        # Record as a module-level import dependency
                        target_id = Node.make_id(name, "<module>")
                        edges.append(Edge(
                            source_id=module_node.id,
                            target_id=target_id,
                            edge_type="imports",
                        ))
        elif node.type == "import_from_statement":
            module_name_node = node.child_by_field_name("module_name")
            if module_name_node and module_node:
                module_name = _text(module_name_node, source_bytes)
                target_id = Node.make_id(module_name, "<module>")
                edges.append(Edge(
                    source_id=module_node.id,
                    target_id=target_id,
                    edge_type="imports",
                ))
        elif node.type == "class_definition":
            # inheritance
            name_node = node.child_by_field_name("name")
            superclasses = node.child_by_field_name("superclasses")
            if name_node and superclasses:
                cls_name = _text(name_node, source_bytes)
                source_node = node_by_name.get(cls_name)
                for arg in superclasses.children:
                    if arg.type == "identifier":
                        parent_name = _text(arg, source_bytes)
                        target = node_by_name.get(parent_name)
                        if target and source_node:
                            edges.append(Edge(
                                source_id=source_node.id,
                                target_id=target.id,
                                edge_type="inherits",
                            ))
        for child in node.children:
            walk_imports(child)

    # Walk calls per function
    def find_func_scope(node, current_func: Optional[Node] = None):
        if node.type in ("function_definition", "async_function_definition"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, source_bytes)
                # find matching node (check both plain name and qualified)
                matched = node_by_name.get(name)
                if matched is None:
                    # try qualified names
                    for n in nodes:
                        if n.name.endswith(f".{name}"):
                            matched = n
                            break
                current_func = matched or current_func
        walk_calls(node, current_func)
        for child in node.children:
            find_func_scope(child, current_func)

    find_func_scope(tree_root)
    walk_imports(tree_root)
    return edges


# ---------------------------------------------------------------------------
# JavaScript / TypeScript extractor (simplified)
# ---------------------------------------------------------------------------

def _extract_js_nodes(tree_root, source_bytes: bytes, file_path: str) -> list[Node]:
    nodes: list[Node] = []
    source_str = source_bytes.decode("utf-8", errors="replace")

    module_id = Node.make_id(file_path, "<module>")
    module_name = Path(file_path).name or "<module>"
    nodes.append(Node(
        id=module_id, type="module", name=module_name,
        file_path=file_path,
        line_start=1, line_end=source_str.count("\n") + 1,
        content_hash=Node.make_content_hash(source_str),
    ))

    FUNC_TYPES = {
        "function_declaration", "function_expression",
        "arrow_function", "method_definition",
        "generator_function_declaration",
    }
    CLASS_TYPES = {"class_declaration", "class_expression"}

    def get_js_func_name(node) -> Optional[str]:
        name_node = node.child_by_field_name("name")
        if name_node:
            return _text(name_node, source_bytes)
        if node.parent:
            if node.parent.type == "variable_declarator":
                pname = node.parent.child_by_field_name("name")
                if pname:
                    return _text(pname, source_bytes)
            elif node.parent.type == "pair":
                key = node.parent.child_by_field_name("key")
                if key:
                    return _text(key, source_bytes)
            elif node.parent.type == "assignment_expression":
                left = node.parent.child_by_field_name("left")
                if left:
                    return _text(left, source_bytes)
            elif node.parent.type == "export_statement":
                return Path(file_path).stem or "default"
        return None

    def walk(node, class_name: Optional[str] = None):
        if node.type in FUNC_TYPES:
            name = get_js_func_name(node)
            if name:  # Skip anonymous unnamed callbacks to avoid graph noise
                qualified = f"{class_name}.{name}" if class_name else name
                node_text = _text(node, source_bytes)
                nodes.append(Node(
                    id=Node.make_id(file_path, qualified),
                    type="method" if class_name or node.type == "method_definition" else "function",
                    name=qualified,
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    content_hash=Node.make_content_hash(node_text),
                ))
            for child in node.children:
                walk(child, class_name)
        elif node.type in CLASS_TYPES:
            name_node = node.child_by_field_name("name")
            cls_name = _text(name_node, source_bytes) if name_node else Path(file_path).stem
            cls_text = _text(node, source_bytes)
            nodes.append(Node(
                id=Node.make_id(file_path, cls_name),
                type="class",
                name=cls_name,
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                content_hash=Node.make_content_hash(cls_text),
            ))
            for child in node.children:
                walk(child, cls_name)
        else:
            for child in node.children:
                walk(child, class_name)

    walk(tree_root)
    return nodes


def _extract_js_edges(tree_root, source_bytes: bytes, file_path: str, nodes: list[Node]) -> list[Edge]:
    edges: list[Edge] = []
    node_by_name: dict[str, Node] = {n.name: n for n in nodes}
    module_node = node_by_name.get("<module>")

    def walk_calls(node, current_func: Optional[Node]):
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee_name = None
                if func_node.type == "identifier":
                    callee_name = _text(func_node, source_bytes)
                elif func_node.type == "member_expression":
                    prop = func_node.child_by_field_name("property")
                    if prop:
                        callee_name = _text(prop, source_bytes)

                if callee_name:
                    target = node_by_name.get(callee_name)
                    if target and current_func and target.id != current_func.id:
                        edges.append(Edge(
                            source_id=current_func.id,
                            target_id=target.id,
                            edge_type="calls",
                        ))
        for child in node.children:
            walk_calls(child, current_func)

    def walk_imports(node):
        if node.type in ("import_statement", "import_declaration"):
            source_node = node.child_by_field_name("source")
            target_str = _text(source_node, source_bytes).strip("'\"") if source_node else _text(node, source_bytes)
            target_id = Node.make_id(target_str, "<module>")
            src_id = module_node.id if module_node else Node.make_id(file_path, "<module>")
            edges.append(Edge(
                source_id=src_id,
                target_id=target_id,
                edge_type="imports",
            ))
        for child in node.children:
            walk_imports(child)

    def find_func_scope(node, current_func: Optional[Node] = None):
        if node.type in ("function_declaration", "generator_function_declaration", "method_definition"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, source_bytes)
                current_func = node_by_name.get(name, current_func)
        elif node.type in ("arrow_function", "function_expression"):
            if node.parent and node.parent.type == "variable_declarator":
                pname = node.parent.child_by_field_name("name")
                if pname:
                    name = _text(pname, source_bytes)
                    current_func = node_by_name.get(name, current_func)

        walk_calls(node, current_func)
        for child in node.children:
            find_func_scope(child, current_func)

    find_func_scope(tree_root)
    walk_imports(tree_root)
    return edges


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_file(path: str) -> list[Node]:
    """Parse a source file with tree-sitter and extract Node records.

    Supports Python, JavaScript, TypeScript, TSX, JSX.
    """
    lang = detect_language(path)
    if lang is None:
        logger.debug("parse_file: unsupported extension for %s", path)
        return []

    try:
        source_bytes = Path(path).read_bytes()
    except OSError as exc:
        logger.warning("parse_file: cannot read %s: %s", path, exc)
        return []

    try:
        parser = _get_parser(lang)
        tree = parser.parse(source_bytes)
    except Exception as exc:
        logger.warning("parse_file: tree-sitter parse failed for %s: %s", path, exc)
        return []

    if lang == "python":
        return _extract_python_nodes(tree.root_node, source_bytes, path)
    else:
        return _extract_js_nodes(tree.root_node, source_bytes, path)


def extract_edges(path: str, nodes: list[Node]) -> list[Edge]:
    """Extract call/import/inheritance edges from a source file."""
    lang = detect_language(path)
    if lang is None or not nodes:
        return []

    try:
        source_bytes = Path(path).read_bytes()
        parser = _get_parser(lang)
        tree = parser.parse(source_bytes)
    except Exception as exc:
        logger.warning("extract_edges: failed for %s: %s", path, exc)
        return []

    if lang == "python":
        return _extract_python_edges(tree.root_node, source_bytes, path, nodes)
    else:
        return _extract_js_edges(tree.root_node, source_bytes, path, nodes)
