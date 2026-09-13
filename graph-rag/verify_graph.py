from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from ingestion.phase1_scan import parse_project_paths
from ingestion.scanner import compare_inventory, tracked_inventory

load_dotenv(CURRENT_DIR / ".env")


def graph_inventory(driver: GraphDatabase.driver, project: str) -> dict[str, list[dict]]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (node)
            WHERE node.project = $project
              AND ((node:Class AND node.file_path IS NOT NULL) OR node:Document)
            RETURN node.relative_path AS relative_path,
                   CASE WHEN node:Class THEN 'Class' ELSE 'Document' END AS node_label,
                   node.content_hash AS content_hash,
                   node.parser_version AS parser_version,
                   node.schema_version AS schema_version
            """,
            project=project,
        )
        inventory: dict[str, list[dict]] = {}
        for record in result:
            relative_path = record["relative_path"]
            if relative_path:
                inventory.setdefault(relative_path, []).append(record.data())
        return inventory


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check local Graph RAG connectivity and file-inventory coverage."
    )
    parser.add_argument("--connection", action="store_true", help="Check Neo4j connectivity only.")
    parser.add_argument(
        "--check", action="store_true", help="Compare graph paths with each configured project's Git inventory."
    )
    args = parser.parse_args()

    if not args.connection and not args.check:
        parser.error("choose --connection or --check")

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "password123"),
        ),
    )
    try:
        driver.verify_connectivity()
        if args.connection:
            print("Neo4j connectivity verified.")
            return

        projects = parse_project_paths(os.getenv("PROJECT_PATHS", "."), CURRENT_DIR)
        any_drift = False

        for project, repo_root in projects:
            if not (repo_root / ".git").exists():
                raise RuntimeError(f"Not a Git repository: {repo_root} (project '{project}')")

            expected = tracked_inventory(str(repo_root))
            indexed = graph_inventory(driver, project)
            missing, stale, modified = compare_inventory(expected, indexed)
            print(
                f"[{project}] Graph coverage: expected={len(expected)} indexed={len(indexed)} "
                f"missing={len(missing)} stale={len(stale)} modified={len(modified)}"
            )
            for label, paths in (
                ("Missing", sorted(missing)),
                ("Stale", sorted(stale)),
                (
                    "Modified",
                    [f"{path} ({', '.join(modified[path])})" for path in sorted(modified)],
                ),
            ):
                if paths:
                    print(f"  {label}:")
                    for path in paths:
                        print(f"    - {path}")
            if missing or stale or modified:
                any_drift = True

        if any_drift:
            raise SystemExit(3)
    finally:
        driver.close()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
