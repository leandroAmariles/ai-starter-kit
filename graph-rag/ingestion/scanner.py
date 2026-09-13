from __future__ import annotations

import subprocess
from pathlib import Path

GRAPH_SCHEMA_VERSION = "5"
JAVA_PARSER_VERSION = "java-tree-sitter-v3"
DOCUMENT_PARSER_VERSION = "generic-bounded-v2"

# Java receives AST parsing. Every other tracked file is a generic Document.
CODE_EXTENSIONS = {".java"}


def scan_repo(root: str, file_inventory: dict[str, dict] | None = None) -> list[Path]:
    """Return tracked Java files for AST parsing."""
    inventory = file_inventory or tracked_inventory(root)
    return [
        metadata["path"]
        for metadata in inventory.values()
        if metadata["node_label"] == "Class" and metadata["path"].is_file()
    ]


def scan_documents(root: str, file_inventory: dict[str, dict] | None = None) -> list[Path]:
    """Return every tracked non-Java file for generic document ingestion."""
    inventory = file_inventory or tracked_inventory(root)
    return [
        metadata["path"]
        for metadata in inventory.values()
        if metadata["node_label"] == "Document" and metadata["path"].is_file()
    ]


def tracked_inventory(root: str) -> dict[str, dict]:
    """Return metadata for paths reported by ``git ls-files --cached`` only."""
    repo_root = Path(root).resolve()
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--cached", "-z"],
        check=True,
        capture_output=True,
    )
    relative_paths = sorted(
        path.decode("utf-8", errors="surrogateescape")
        for path in result.stdout.split(b"\0")
        if path
    )

    inventory: dict[str, dict] = {}
    for relative_path in relative_paths:
        path = repo_root / relative_path
        if not path.is_file():
            continue
        node_label = "Class" if path.suffix.lower() in CODE_EXTENSIONS else "Document"
        inventory[relative_path] = {
            "path": path.resolve(),
            "relative_path": relative_path,
            "node_label": node_label,
            "content_hash": _working_tree_blob_hash(repo_root, relative_path),
            "parser_version": (
                JAVA_PARSER_VERSION if node_label == "Class" else DOCUMENT_PARSER_VERSION
            ),
            "schema_version": GRAPH_SCHEMA_VERSION,
        }
    return inventory


def graph_metadata(file_metadata: dict) -> dict[str, str]:
    """Return the metadata persisted on Class and Document nodes."""
    return {
        "relative_path": file_metadata["relative_path"],
        "content_hash": file_metadata["content_hash"],
        "parser_version": file_metadata["parser_version"],
        "schema_version": file_metadata["schema_version"],
    }


def compare_inventory(
    expected: dict[str, dict], indexed: dict[str, list[dict]]
) -> tuple[set[str], set[str], dict[str, list[str]]]:
    """Return missing, stale, and modified paths with modification reasons."""
    expected_paths = set(expected)
    indexed_paths = set(indexed)
    missing = expected_paths - indexed_paths
    stale = indexed_paths - expected_paths
    modified: dict[str, list[str]] = {}

    for relative_path in sorted(expected_paths & indexed_paths):
        expected_metadata = expected[relative_path]
        indexed_nodes = indexed[relative_path]
        reasons: list[str] = []
        if len(indexed_nodes) != 1:
            reasons.append(f"node_count={len(indexed_nodes)}")
        for node in indexed_nodes:
            if node.get("node_label") != expected_metadata["node_label"]:
                reasons.append("node_label")
            for property_name in ("content_hash", "parser_version", "schema_version"):
                if node.get(property_name) != expected_metadata[property_name]:
                    reasons.append(property_name)
        if reasons:
            modified[relative_path] = sorted(set(reasons))

    return missing, stale, modified


def _working_tree_blob_hash(repo_root: Path, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "hash-object", "--", relative_path],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
