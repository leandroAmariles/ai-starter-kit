from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CURRENT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from ingestion.graph_ingestor import GraphIngestor
from ingestion.infra_config import resolve_stream_destinations, scan_datasources
from ingestion.maven_coordinates import read_project_coordinates
from ingestion.neo4j_safety import require_local_ingestion
from ingestion.parsers.java_parser import parse_java_file
from ingestion.parsers.generic_file_parser import extract_local_references, parse_generic_file
from ingestion.scanner import graph_metadata, scan_documents, scan_repo, tracked_inventory
from ingestion.task_generator import generate_pipeline_tasks

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    # Windows terminals default stdout to cp1252, which can't encode the
    # ✅ status marker printed below and crashes the run after ingestion
    # has already completed.
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = PROJECT_DIR / "data"
EXTRACTED_CLASSES_PATH = DATA_DIR / "extracted_classes.json"
PIPELINE_TASKS_PATH = PROJECT_DIR / "pipeline_tasks.md"
SETUP_CYPHER_PATH = PROJECT_DIR / "queries" / "neo4j_setup.cypher"

SCOPE_SEPARATOR = "::"
DEFAULT_GROUP = "default"


def _scoped(group: str, project: str, fqn: str) -> str:
    """Prefix a language-level fqn/path with its group and project so it
    stays globally unique in a graph that ingests more than one repository,
    or even several unrelated *systems* of repositories (see PROJECT_GROUP
    in graph-rag/.env — this is what lets multiple independent systems share
    one Neo4j container without their node identities colliding)."""
    return f"{group}{SCOPE_SEPARATOR}{project}{SCOPE_SEPARATOR}{fqn}"


def parse_project_paths(raw: str, project_dir: Path) -> list[tuple[str, Path]]:
    """Parse `PROJECT_PATHS` into a list of (project_name, resolved_root).

    Each entry is `name=path` or just `path` (name defaults to the directory's
    basename). Relative paths resolve against the parent of graph-rag/, i.e.
    the repository this kit was installed into.
    """
    host_repo_root = project_dir.parent
    entries: list[tuple[str, Path]] = []
    seen_names: set[str] = set()

    for raw_entry in raw.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue

        if "=" in entry:
            name, _, path_text = entry.partition("=")
            name = name.strip()
            path_text = path_text.strip()
        else:
            name = ""
            path_text = entry

        candidate = Path(path_text)
        resolved = (candidate if candidate.is_absolute() else host_repo_root / candidate).resolve()

        if not name:
            name = resolved.name

        if name in seen_names:
            raise SystemExit(
                f"PROJECT_PATHS has two entries named '{name}'. "
                "Give each project an explicit unique `name=path` entry."
            )
        seen_names.add(name)
        entries.append((name, resolved))

    if not entries:
        raise SystemExit("PROJECT_PATHS is empty. Set it in graph-rag/.env, e.g. PROJECT_PATHS=.")

    return entries


def _resolve_java_reference(parsed_class: dict, reference_name: str) -> str:
    imports = parsed_class.get("imports", [])
    for imported in imports:
        if imported.endswith(f".{reference_name}"):
            return imported

    if "." in reference_name:
        return reference_name

    package_name = parsed_class["fqn"].rsplit(".", 1)[0] if "." in parsed_class["fqn"] else ""
    return f"{package_name}.{reference_name}" if package_name else reference_name


def _run_setup_statements(ingestor: GraphIngestor) -> None:
    content = SETUP_CYPHER_PATH.read_text(encoding="utf-8")
    statements = [statement.strip() for statement in content.split(";") if statement.strip()]
    for statement in statements:
        ingestor.execute_statement(statement)


def _merge_stream_topics(parsed_classes: list[dict], repo_root: Path) -> None:
    """Resolve each class's Spring Cloud Stream binding names (`stream_bindings_in`/
    `_out`, produced by java_parser from `@Bean Consumer/Function/Supplier` methods
    and `streamBridge.send("binding")` calls) to real topic names via this project's
    `application*.yml`, and fold them into the same `kafka_consumes`/`kafka_produces`
    lists used by direct spring-kafka usage — downstream code doesn't need to know
    which of the two Kafka integration styles a class actually uses."""
    destinations = resolve_stream_destinations(repo_root)
    for parsed in parsed_classes:
        for binding in parsed.get("stream_bindings_in", []):
            topic = destinations.get(binding)
            if topic:
                parsed["kafka_consumes"] = sorted(set(parsed.get("kafka_consumes", [])) | {topic})
        for binding in parsed.get("stream_bindings_out", []):
            topic = destinations.get(binding)
            if topic:
                parsed["kafka_produces"] = sorted(set(parsed.get("kafka_produces", [])) | {topic})


def _ingest_project(
    ingestor: GraphIngestor, group: str, project: str, repo_root: Path, reset: bool
) -> tuple[list[dict], int, tuple[set, set], list[tuple[str, str]]]:
    """Ingest one repository, scoped to `(group, project)`. Returns
    (parsed_classes with unscoped fqns, relations_created, provided/required
    Maven coordinates, [(scoped_class_fqn, feign_target_name), ...])."""
    if not (repo_root / ".git").exists():
        raise SystemExit(f"Not a Git repository: {repo_root} (project '{project}')")

    if reset:
        ingestor.execute_statement(
            "MATCH (n) WHERE n.project = $project AND n.group = $group DETACH DELETE n",
            {"project": project, "group": group},
        )

    ingestor.upsert_project(project, str(repo_root), group)

    initial_inventory = tracked_inventory(str(repo_root))
    repo_files = scan_repo(str(repo_root), initial_inventory)
    parsed_classes: list[dict] = []
    for file_path in tqdm(repo_files, desc=f"[{project}] Parsing files", unit="file"):
        parsed = parse_java_file(str(file_path))
        if parsed is None:
            continue
        relative_path = file_path.relative_to(repo_root).as_posix()
        parsed.update(graph_metadata(initial_inventory[relative_path]))
        parsed["project"] = project
        parsed["group"] = group
        parsed_classes.append(parsed)

    # Re-hash after this run's own generated files (e.g. pipeline_tasks.md) may
    # have changed the working tree, mirroring the single-repo behaviour.
    final_inventory = tracked_inventory(str(repo_root))
    for parsed in parsed_classes:
        parsed.update(graph_metadata(final_inventory[parsed["relative_path"]]))

    doc_files = scan_documents(str(repo_root), final_inventory)
    parsed_documents: list[dict] = []
    for file_path in tqdm(doc_files, desc=f"[{project}] Parsing documents", unit="file"):
        parsed_doc = parse_generic_file(str(file_path), repo_root)
        if parsed_doc is None:
            continue
        parsed_doc.update(graph_metadata(final_inventory[parsed_doc["relative_path"]]))
        parsed_doc["project"] = project
        parsed_doc["group"] = group
        parsed_documents.append(parsed_doc)

    missing_before, stale_before, modified_before = ingestor.reconcile_inventory(
        project, group, final_inventory
    )

    _merge_stream_topics(parsed_classes, repo_root)

    for datasource in scan_datasources(repo_root):
        ingestor.link_project_database(project, datasource["engine"], datasource["database"], group)

    scoped_classes = []
    for parsed in parsed_classes:
        scoped = dict(parsed)
        scoped["fqn"] = _scoped(group, project, parsed["fqn"])
        scoped_classes.append(scoped)
        ingestor.upsert_node(scoped)

    scoped_documents = []
    for parsed_doc in parsed_documents:
        scoped = dict(parsed_doc)
        scoped["fqn"] = _scoped(group, project, parsed_doc["fqn"])
        scoped_documents.append(scoped)
        ingestor.upsert_document(scoped)

    relations_created = 0
    feign_targets: list[tuple[str, str]] = []
    for parsed in parsed_classes:
        source_fqn = _scoped(group, project, parsed["fqn"])
        ingestor.link_belongs_to(source_fqn, project, group)

        for annotation in parsed.get("annotations", []):
            ingestor.upsert_annotation(source_fqn, annotation)
            relations_created += 1

        for interface_name in parsed.get("implements", []):
            target = _resolve_java_reference(parsed, interface_name)
            if target != parsed["fqn"]:
                ingestor.upsert_relation(source_fqn, _scoped(group, project, target), "IMPLEMENTS")
                relations_created += 1

        parent_name = parsed.get("extends")
        if parent_name:
            target = _resolve_java_reference(parsed, parent_name)
            if target != parsed["fqn"]:
                ingestor.upsert_relation(source_fqn, _scoped(group, project, target), "EXTENDS")
                relations_created += 1

        for imported in parsed.get("imports", []):
            if imported and imported != parsed["fqn"]:
                ingestor.upsert_relation(source_fqn, _scoped(group, project, imported), "DEPENDS_ON")
                relations_created += 1

        for topic in parsed.get("kafka_consumes", []):
            ingestor.upsert_topic_relation(source_fqn, topic, "consumes", group)
            relations_created += 1

        for topic in parsed.get("kafka_produces", []):
            ingestor.upsert_topic_relation(source_fqn, topic, "produces", group)
            relations_created += 1

        feign_target = parsed.get("feign_target")
        if feign_target:
            feign_targets.append((source_fqn, feign_target))

    for parsed_doc in parsed_documents:
        ingestor.link_belongs_to(_scoped(group, project, parsed_doc["fqn"]), project, group)

    known_paths = set(final_inventory)
    document_references_created = 0
    for parsed_doc in parsed_documents:
        file_path = Path(parsed_doc["file_path"])
        references = extract_local_references(
            file_path, parsed_doc["content"], repo_root, known_paths
        )
        source_fqn = _scoped(group, project, parsed_doc["fqn"])
        for reference in references:
            if ingestor.upsert_document_reference(project, source_fqn, reference):
                document_references_created += 1

    print(
        f"[{project}] Scanned {len(repo_files)} code files, extracted {len(parsed_classes)} classes, "
        f"created {relations_created} relations"
    )
    print(
        f"[{project}] Indexed {len(parsed_documents)} config/document files as :Document nodes, "
        f"created {document_references_created} document references"
    )
    print(
        f"[{project}] Reconciled prior graph inventory: "
        f"missing={len(missing_before)} stale={len(stale_before)} modified={len(modified_before)}"
    )

    coordinates = read_project_coordinates(repo_root, list(final_inventory))
    return parsed_classes, relations_created, coordinates, feign_targets


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local, multi-project Graph RAG index.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete each configured project's existing graph nodes before indexing it.",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_DIR / ".env")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    require_local_ingestion(neo4j_uri)

    group = os.getenv("PROJECT_GROUP", DEFAULT_GROUP).strip() or DEFAULT_GROUP
    projects = parse_project_paths(os.getenv("PROJECT_PATHS", "."), PROJECT_DIR)

    ingestor = GraphIngestor(
        neo4j_uri,
        os.getenv("NEO4J_USER", "neo4j"),
        os.getenv("NEO4J_PASSWORD", "password123"),
    )

    all_parsed_classes: list[dict] = []
    coordinates_by_project: dict[str, tuple[set, set]] = {}
    feign_targets_by_project: dict[str, list[tuple[str, str]]] = {}

    try:
        _run_setup_statements(ingestor)

        for project, repo_root in projects:
            parsed_classes, _relations, coordinates, feign_targets = _ingest_project(
                ingestor, group, project, repo_root, args.reset
            )
            for parsed in parsed_classes:
                scoped = dict(parsed)
                scoped["fqn"] = _scoped(group, project, parsed["fqn"])
                all_parsed_classes.append(scoped)
            coordinates_by_project[project] = coordinates
            feign_targets_by_project[project] = feign_targets

        # ── Cross-project edges: A DEPENDS_ON_PROJECT B iff A requires a Maven
        # coordinate that B publishes. Deterministic, no false positives, and
        # only meaningful when the depended-upon project is also configured
        # in PROJECT_PATHS (so its own coordinates were actually read).
        dependency_edges = 0
        for project_a, (_, required_a) in coordinates_by_project.items():
            for project_b, (provided_b, _) in coordinates_by_project.items():
                if project_a == project_b or not provided_b:
                    continue
                if required_a & provided_b:
                    ingestor.upsert_project_dependency(project_a, project_b, group)
                    dependency_edges += 1

        # ── CALLS_SERVICE: a @FeignClient(name="X") is only linked to a real
        # :Project node when X matches a project actually configured in
        # PROJECT_PATHS (verified, like DEPENDS_ON_PROJECT above); otherwise
        # it links to an :ExternalService node, since the target wasn't
        # confirmed to be present in this graph.
        known_project_names = {name for name, _ in projects}
        service_call_edges = 0
        for feign_targets in feign_targets_by_project.values():
            for class_fqn, target_name in feign_targets:
                verified = target_name in known_project_names
                ingestor.upsert_service_call(class_fqn, target_name, verified, group)
                service_call_edges += 1

        # ── SHARES_DATABASE: two different projects resolve to the identical
        # (engine, database name) pair from their own application*.yml. Each
        # project's USES_DATABASE edge already points at the same merged
        # :Database node in that case; this just adds the direct Project-to-
        # Project edge so it doesn't require a 2-hop query to notice.
        datasources_by_project = {
            project: scan_datasources(repo_root) for project, repo_root in projects
        }
        shared_database_edges = 0
        seen_pairs: set[frozenset[str]] = set()
        for project_a, datasources_a in datasources_by_project.items():
            for project_b, datasources_b in datasources_by_project.items():
                if project_a == project_b:
                    continue
                pair_key = frozenset((project_a, project_b))
                if pair_key in seen_pairs:
                    continue
                common = {
                    (ds["engine"], ds["database"]) for ds in datasources_a
                } & {(ds["engine"], ds["database"]) for ds in datasources_b}
                for engine, database in common:
                    ingestor.upsert_shared_database(project_a, project_b, engine, database, group)
                    shared_database_edges += 1
                if common:
                    seen_pairs.add(pair_key)

        ingestor.cleanup_orphans()

        EXTRACTED_CLASSES_PATH.write_text(
            json.dumps(all_parsed_classes, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        generate_pipeline_tasks(str(EXTRACTED_CLASSES_PATH), str(PIPELINE_TASKS_PATH))

        print(
            f"Ingested {len(projects)} project(s) in group '{group}': "
            f"{', '.join(name for name, _ in projects)}"
        )
        print(f"Cross-project DEPENDS_ON_PROJECT edges: {dependency_edges}")
        print(f"Cross-project CALLS_SERVICE edges: {service_call_edges}")
        print(f"Cross-project SHARES_DATABASE edges: {shared_database_edges}")
        print("✅ Phase 1 complete. Ask your AI agent to execute pipeline_tasks.md to generate data/summaries.json")
    finally:
        ingestor.close()


if __name__ == "__main__":
    main()
