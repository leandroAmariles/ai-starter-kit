from __future__ import annotations

import re
from pathlib import Path

# Max content size to store in Neo4j (avoids bloating properties with huge files)
MAX_CONTENT_BYTES = 32_000

DOCUMENT_TYPE_MAP = {
    ".yaml": "config",
    ".yml": "config",
    ".json": "config",
    ".xml": "config",
    ".properties": "config",
    ".md": "document",
    ".adoc": "document",
}

# Binary files are mapped as metadata only, so the graph can represent the
# complete project without storing non-text content in Neo4j.
BINARY_EXTENSIONS = {
    ".class",
    ".gif",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".ttf",
    ".woff",
    ".woff2",
    ".zip",
}

MARKDOWN_LINK_PATTERN = re.compile(r"\]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)")
INLINE_PATH_PATTERN = re.compile(
    r"`((?:\.\.?/)?(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9_-]+)?)`"
)


def parse_generic_file(file_path: str, repo_root: Path) -> dict | None:
    path = Path(file_path)
    suffix = path.suffix.lower()
    doc_type = DOCUMENT_TYPE_MAP.get(suffix, "file")

    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_CONTENT_BYTES + 1)
        is_binary = suffix in BINARY_EXTENSIONS or b"\x00" in raw[:MAX_CONTENT_BYTES]
        content_bytes = raw[:MAX_CONTENT_BYTES]
        content = "" if is_binary else content_bytes.decode("utf-8", errors="replace")
        truncated = len(raw) > MAX_CONTENT_BYTES
    except OSError:
        return None

    try:
        relative = path.relative_to(repo_root).as_posix()
    except ValueError:
        relative = path.as_posix()

    # fqn is the repo-relative path used as unique identifier
    fqn = relative

    return {
        "fqn": fqn,
        "name": path.name,
        "file_path": str(path),
        "relative_path": relative,
        "language": suffix.lstrip("."),
        "type": doc_type,
        "content": content,
        "truncated": truncated,
        "binary": is_binary,
    }


def extract_local_references(
        document_path: Path, content: str, repo_root: Path, known_paths: set[str]) -> set[str]:
    """Resolve Markdown links and inline local paths to tracked project files."""
    references = set(MARKDOWN_LINK_PATTERN.findall(content))
    references.update(INLINE_PATH_PATTERN.findall(content))

    resolved_references = set()
    for reference in references:
        target = _resolve_local_reference(document_path, reference, repo_root)
        if target in known_paths:
            resolved_references.add(target)
    return resolved_references


def _resolve_local_reference(document_path: Path, reference: str, repo_root: Path) -> str | None:
    if "://" in reference or reference.startswith(("#", "mailto:")):
        return None

    path_text = reference.split("#", 1)[0].split("?", 1)[0]
    if not path_text:
        return None

    candidate = (document_path.parent / path_text).resolve()
    try:
        return candidate.relative_to(repo_root).as_posix()
    except ValueError:
        return None
