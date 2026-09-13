from __future__ import annotations

import re
import sys
from pathlib import Path

from tree_sitter import Node
from tree_sitter_languages import get_language, get_parser

LANGUAGE = get_language("java")
PARSER = get_parser("java")

PACKAGE_QUERY = LANGUAGE.query(
    """
    (package_declaration
      (scoped_identifier) @package)
    """
)

IMPORT_QUERY = LANGUAGE.query(
    """
    (import_declaration
      (scoped_identifier) @import)
    """
)

DECLARATION_QUERY = LANGUAGE.query(
    """
    (class_declaration) @decl
    (interface_declaration) @decl
    (enum_declaration) @decl
    (record_declaration) @decl
    """
)

TYPE_MAPPING = {
    "class_declaration": "CLASS",
    "interface_declaration": "INTERFACE",
    "enum_declaration": "ENUM",
    "record_declaration": "RECORD",
}


def _node_text(node: Node | None, source: bytes) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8").strip()


def _extract_annotation_name(node: Node, source: bytes) -> str | None:
    raw = _node_text(node, source)
    if not raw.startswith("@"):
        return None
    raw = raw[1:].split("(", 1)[0].strip()
    if not raw:
        return None
    return raw.split(".")[-1]


def _split_type_names(raw: str) -> list[str]:
    cleaned = re.sub(r"^\s*(implements|extends)\s+", "", raw).strip()
    if not cleaned:
        return []
    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    names: list[str] = []
    for part in parts:
        part = re.sub(r"<.*?>", "", part)
        part = part.split()[-1]
        if part:
            names.append(part.split(".")[-1])
    return names


def _collect_annotation_names(declaration: Node, source: bytes) -> list[str]:
    annotations: list[str] = []
    for child in declaration.children:
        if child.type != "modifiers":
            continue
        for modifier_child in child.named_children:
            if modifier_child.type not in {"annotation", "marker_annotation"}:
                continue
            annotation_name = _extract_annotation_name(modifier_child, source)
            if annotation_name:
                annotations.append(annotation_name)
    return annotations


CONST_STRING_PATTERN = re.compile(
    r"(?:private|protected|public)?\s*static\s+final\s+String\s+(\w+)\s*=\s*\"([^\"]*)\"\s*;"
)

KAFKA_LISTENER_PATTERN = re.compile(r"@KafkaListener\s*\(([^)]*)\)")
KAFKA_LISTENER_TOPICS_PATTERN = re.compile(r"topics\s*=\s*(\{[^}]*\}|\"[^\"]+\"|\w+)")
KAFKA_TEMPLATE_SEND_PATTERN = re.compile(r"\bkafkaTemplate\s*\.\s*send\s*\(\s*([^,)]+)")
KAFKA_HEADER_TOPIC_PATTERN = re.compile(r"KafkaHeaders\s*\.\s*TOPIC\s*,\s*([^,)]+)")
PRODUCER_RECORD_PATTERN = re.compile(r"new\s+ProducerRecord\s*<[^>]*>\s*\(\s*([^,)]+)")

BEAN_FUNCTION_PATTERN = re.compile(
    r"@Bean\b[\s\S]{0,300}?\b(Consumer|Function|Supplier)\s*<[^>]*>\s+(\w+)\s*\("
)
STREAM_BRIDGE_SEND_PATTERN = re.compile(r"\bstreamBridge\s*\.\s*send\s*\(\s*\"([^\"]+)\"")

REST_MAPPING_PATTERN = re.compile(
    r"@(?:Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*)?\"([^\"]+)\""
)
FEIGN_CLIENT_PATTERN = re.compile(
    r"@FeignClient\s*\(([^)]*)\)"
)
FEIGN_CLIENT_ATTR_PATTERN = re.compile(r"(?:name|value)\s*=\s*\"([^\"]+)\"")
FEIGN_CLIENT_BARE_PATTERN = re.compile(r"^\s*\"([^\"]+)\"\s*$")


def _resolve_token(token: str, constants: dict[str, str]) -> str | None:
    """Resolve a Java expression fragment to a literal string, if possible.

    Handles the two shapes actually used for topic names in this codebase:
    an inline string literal, or a `private static final String X = "...";`
    constant referenced by name. Anything else (a variable, a built Message
    object, a method call) resolves to None and is silently skipped rather
    than guessed — consistent with this pipeline's "verify, don't fabricate"
    approach to relationships.
    """
    token = token.strip()
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    return constants.get(token)


def _extract_kafka_topics(source_text: str, constants: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (consumed_topics, produced_topics) from direct spring-kafka usage
    (`@KafkaListener`, `KafkaTemplate.send`, `KafkaHeaders.TOPIC`, `ProducerRecord`).
    Spring Cloud Stream function bindings are handled separately, by name, and
    resolved to real topics later using each project's `application*.yml`.
    """
    consumed: list[str] = []
    for match in KAFKA_LISTENER_PATTERN.finditer(source_text):
        args = match.group(1)
        topics_match = KAFKA_LISTENER_TOPICS_PATTERN.search(args)
        if not topics_match:
            continue
        raw = topics_match.group(1)
        tokens = [t.strip() for t in raw.strip("{}").split(",")] if raw.startswith("{") else [raw]
        for token in tokens:
            resolved = _resolve_token(token, constants)
            if resolved:
                consumed.append(resolved)

    produced: list[str] = []
    for pattern in (KAFKA_TEMPLATE_SEND_PATTERN, KAFKA_HEADER_TOPIC_PATTERN, PRODUCER_RECORD_PATTERN):
        for match in pattern.finditer(source_text):
            resolved = _resolve_token(match.group(1), constants)
            if resolved:
                produced.append(resolved)

    return sorted(set(consumed)), sorted(set(produced))


def _extract_stream_bindings(source_text: str) -> tuple[list[str], list[str]]:
    """Return (in_bindings, out_bindings): Spring Cloud Stream binding names,
    e.g. "ticketCategorizationRequests-in-0". These are names, not topics —
    resolving them to real topic names requires `spring.cloud.stream.bindings.
    <name>.destination` from application*.yml, done at the project level
    (see ingestion.infra_config.resolve_stream_destinations)."""
    in_bindings: list[str] = []
    out_bindings: list[str] = []

    for match in BEAN_FUNCTION_PATTERN.finditer(source_text):
        kind, name = match.group(1), match.group(2)
        if kind in ("Consumer", "Function"):
            in_bindings.append(f"{name}-in-0")
        if kind in ("Supplier", "Function"):
            out_bindings.append(f"{name}-out-0")

    for match in STREAM_BRIDGE_SEND_PATTERN.finditer(source_text):
        out_bindings.append(match.group(1))

    return sorted(set(in_bindings)), sorted(set(out_bindings))


def _extract_rest_endpoints(source_text: str, annotations: list[str]) -> list[str]:
    """Return literal HTTP paths for controller classes only. Paths are
    collected as-is (class-level base path and method-level paths mixed
    together, no prefix-stitching) — enough to see "this class exposes these
    routes" without risking a wrongly-concatenated path."""
    if "RestController" not in annotations and "Controller" not in annotations:
        return []
    return sorted(set(REST_MAPPING_PATTERN.findall(source_text)))


def _extract_feign_target(source_text: str) -> str | None:
    """Return the target service name declared in `@FeignClient(name=...)` /
    `@FeignClient("...")`, if present. This is the only outbound-REST signal
    considered reliable enough to model: WebClient/RestTemplate base URLs are
    typically built from injected config, not literals, so guessing them
    would risk fabricating a relationship that isn't really there."""
    match = FEIGN_CLIENT_PATTERN.search(source_text)
    if not match:
        return None
    args = match.group(1)
    attr_match = FEIGN_CLIENT_ATTR_PATTERN.search(args)
    if attr_match:
        return attr_match.group(1)
    bare_match = FEIGN_CLIENT_BARE_PATTERN.match(args)
    return bare_match.group(1) if bare_match else None


def _collect_relationships(declaration: Node, source: bytes) -> tuple[list[str], str | None]:
    implements: list[str] = []
    extends: str | None = None

    for child in declaration.children:
        if child.type == "super_interfaces":
            implements.extend(_split_type_names(_node_text(child, source)))
        elif child.type == "extends_interfaces":
            implements.extend(_split_type_names(_node_text(child, source)))
        elif child.type == "superclass":
            candidates = _split_type_names(_node_text(child, source))
            extends = candidates[0] if candidates else None

    return implements, extends


def parse_java_file(path: str) -> dict | None:
    file_path = Path(path).resolve()

    try:
        source = file_path.read_bytes()
        tree = PARSER.parse(source)
        root = tree.root_node
        if root.type != "program" or root.has_error:
            print(f"WARN: Could not parse Java file {file_path}", file=sys.stderr)
            return None

        package_matches = PACKAGE_QUERY.captures(root)
        imports = [_node_text(node, source) for node, _ in IMPORT_QUERY.captures(root)]
        declarations = DECLARATION_QUERY.captures(root)

        if not declarations:
            return None

        declaration = declarations[0][0]
        class_name = _node_text(declaration.child_by_field_name("name"), source)
        class_type = TYPE_MAPPING.get(declaration.type)
        if not class_name or class_type is None:
            print(f"WARN: Could not extract Java declaration from {file_path}", file=sys.stderr)
            return None

        package_name = _node_text(package_matches[0][0], source) if package_matches else ""
        annotations = _collect_annotation_names(declaration, source)
        implements, extends = _collect_relationships(declaration, source)
        fqn = f"{package_name}.{class_name}" if package_name else class_name

        source_text = source.decode("utf-8", errors="replace")
        constants = {m.group(1): m.group(2) for m in CONST_STRING_PATTERN.finditer(source_text)}
        kafka_consumes, kafka_produces = _extract_kafka_topics(source_text, constants)
        stream_in, stream_out = _extract_stream_bindings(source_text)

        return {
            "fqn": fqn,
            "name": class_name,
            "type": class_type,
            "annotations": annotations,
            "implements": implements,
            "extends": extends,
            "imports": imports,
            "file_path": str(file_path),
            "language": "java",
            "kafka_consumes": kafka_consumes,
            "kafka_produces": kafka_produces,
            "stream_bindings_in": stream_in,
            "stream_bindings_out": stream_out,
            "rest_endpoints": _extract_rest_endpoints(source_text, annotations),
            "feign_target": _extract_feign_target(source_text),
        }
    except Exception:
        print(f"WARN: Could not parse Java file {file_path}", file=sys.stderr)
        return None
