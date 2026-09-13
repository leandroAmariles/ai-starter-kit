from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

Coordinate = tuple[str, str]


def _strip_namespace(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _child(element: ET.Element, tag: str) -> ET.Element | None:
    for child in element:
        if _strip_namespace(child.tag) == tag:
            return child
    return None


def _child_text(element: ET.Element, tag: str) -> str | None:
    child = _child(element, tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def _dependencies_in(container: ET.Element | None) -> set[Coordinate]:
    if container is None:
        return set()
    found: set[Coordinate] = set()
    for dependency in container:
        if _strip_namespace(dependency.tag) != "dependency":
            continue
        group = _child_text(dependency, "groupId")
        artifact = _child_text(dependency, "artifactId")
        if group and artifact:
            found.add((group, artifact))
    return found


def parse_pom(pom_path: Path) -> tuple[Coordinate | None, set[Coordinate]]:
    """Return (this pom's own coordinate, every dependency coordinate it declares)."""
    try:
        root = ET.parse(pom_path).getroot()
    except (ET.ParseError, OSError):
        return None, set()

    group_id = _child_text(root, "groupId")
    artifact_id = _child_text(root, "artifactId")
    if group_id is None:
        parent = _child(root, "parent")
        if parent is not None:
            group_id = _child_text(parent, "groupId")

    provided = (group_id, artifact_id) if group_id and artifact_id else None

    required = _dependencies_in(_child(root, "dependencies"))
    dependency_management = _child(root, "dependencyManagement")
    if dependency_management is not None:
        required |= _dependencies_in(_child(dependency_management, "dependencies"))

    return provided, required


def read_project_coordinates(
    repo_root: Path, tracked_relative_paths: list[str]
) -> tuple[set[Coordinate], set[Coordinate]]:
    """Return (provided, required) Maven coordinates across every tracked pom.xml in a repo.

    `provided` is what this project publishes (its own modules' groupId:artifactId).
    `required` is every dependency coordinate declared anywhere in the project.
    Used to derive deterministic cross-project DEPENDS_ON_PROJECT edges: if project
    A requires a coordinate that project B provides, A depends on B.
    """
    provided: set[Coordinate] = set()
    required: set[Coordinate] = set()

    for relative_path in tracked_relative_paths:
        if Path(relative_path).name != "pom.xml":
            continue
        pom_provided, pom_required = parse_pom(repo_root / relative_path)
        if pom_provided:
            provided.add(pom_provided)
        required.update(pom_required)

    return provided, required
