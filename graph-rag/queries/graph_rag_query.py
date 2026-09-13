from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CURRENT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from ingestion.embedder import generate_embedding
from ingestion.neo4j_safety import require_local_ingestion

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    # Windows terminals default stdout to cp1252, which can't encode some of
    # the characters agents may pass through in a query or summary.
    sys.stdout.reconfigure(encoding="utf-8")

VECTOR_INDEXES = {
    "Class": "class_summaries_idx",
    "Document": "document_summaries_idx",
}

RELATIONSHIP_TYPES = [
    "IMPLEMENTS",
    "DEPENDS_ON",
    "EXTENDS",
    "PRODUCES_TO",
    "CONSUMES_FROM",
    "CALLS_SERVICE",
]


def _vector_search(
    session, label: str, index_name: str, embedding: list[float], k: int,
    project: str | None, group: str | None,
) -> list[dict]:
    # Over-fetch when filtering client-side in Cypher: the ANN index has no
    # group/project-aware pre-filter, so ask for more candidates than we need
    # and let WHERE narrow them down.
    fetch_k = k * 4 if (project or group) else k
    result = session.run(
        f"""
        CALL db.index.vector.queryNodes($index_name, $fetch_k, $embedding)
        YIELD node, score
        WHERE ($project IS NULL OR node.project = $project)
          AND ($group IS NULL OR node.group = $group)
        RETURN node, score
        ORDER BY score DESC
        LIMIT $k
        """,
        index_name=index_name,
        fetch_k=fetch_k,
        embedding=embedding,
        project=project,
        group=group,
        k=k,
    )
    hits = []
    for record in result:
        node = record["node"]
        hits.append(
            {
                "label": label,
                "score": record["score"],
                "fqn": node.get("fqn"),
                "name": node.get("name"),
                "type": node.get("type"),
                "relative_path": node.get("relative_path"),
                "summary": node.get("summary"),
            }
        )
    return hits


def _related_classes(session, fqn: str, limit: int = 8) -> list[dict]:
    """One-hop outgoing IMPLEMENTS/DEPENDS_ON/EXTENDS edges from a Class node.

    Kept to outgoing edges only: for "what do I need to know to implement
    something like this" (the use case this script is built for), the
    dependencies a class already has are more directly useful than every
    consumer that happens to depend on it.
    """
    result = session.run(
        """
        MATCH (n:Class {fqn: $fqn})-[r]->(m)
        WHERE type(r) IN $rel_types
        RETURN type(r) AS rel, m.fqn AS fqn, m.name AS name, m.type AS type
        LIMIT $limit
        """,
        fqn=fqn,
        rel_types=RELATIONSHIP_TYPES,
        limit=limit,
    )
    return [dict(record) for record in result]


def query_graph(
    session,
    question: str,
    *,
    top_k: int = 8,
    project: str | None = None,
    group: str | None = None,
    labels: tuple[str, ...] = ("Class", "Document"),
    model_name: str = "all-MiniLM-L6-v2",
    expand: bool = True,
) -> list[dict]:
    embedding = generate_embedding(question, model_name=model_name)

    hits: list[dict] = []
    for label in labels:
        index_name = VECTOR_INDEXES[label]
        hits.extend(_vector_search(session, label, index_name, embedding, top_k, project, group))

    hits.sort(key=lambda h: h["score"], reverse=True)
    hits = hits[:top_k]

    if expand:
        for hit in hits:
            if hit["label"] == "Class" and hit["fqn"]:
                hit["related"] = _related_classes(session, hit["fqn"])

    return hits


def format_text(question: str, hits: list[dict]) -> str:
    lines = [f'Query: "{question}"', ""]
    if not hits:
        lines.append("No results. Try a different phrasing, or fall back to repository-local search.")
        return "\n".join(lines)

    for i, hit in enumerate(hits, start=1):
        header = f"{i}. [{hit['score']:.3f}] {hit['label']} {hit['fqn']}"
        if hit.get("relative_path"):
            header += f" ({hit['relative_path']})"
        lines.append(header)
        if hit.get("summary"):
            lines.append(f"   Summary: {hit['summary']}")
        related = hit.get("related") or []
        if related:
            by_rel: dict[str, list[str]] = {}
            for r in related:
                by_rel.setdefault(r["rel"], []).append(r["name"] or r["fqn"])
            for rel, names in by_rel.items():
                lines.append(f"   {rel.title().replace('_', ' ')}: {', '.join(names)}")
        lines.append("")

    lines.append("Graph results are a discovery aid, not source of truth — confirm in the actual files before changing code.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Semantic search over the local Neo4j architecture graph (vector search + 1-hop graph traversal)."
    )
    parser.add_argument("question", help="Natural-language question, e.g. 'Which adapters implement the ticket repository port?'")
    parser.add_argument("--top", type=int, default=8, help="Max results to return (default: 8)")
    parser.add_argument("--project", default=None, help="Restrict results to one ingested project (see PROJECT_PATHS in .env)")
    parser.add_argument(
        "--all-groups",
        action="store_true",
        help=(
            "Search across every PROJECT_GROUP in this Neo4j instance instead of just this "
            "installation's own group (see PROJECT_GROUP in .env). Off by default: if this "
            "instance is shared with other, unrelated systems, you almost never want their "
            "results mixed into this one's."
        ),
    )
    parser.add_argument(
        "--label",
        choices=["class", "document", "both"],
        default="both",
        help="Search Class summaries, Document summaries, or both (default: both)",
    )
    parser.add_argument("--no-expand", action="store_true", help="Skip the 1-hop graph traversal step")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of text")
    args = parser.parse_args()

    load_dotenv(PROJECT_DIR / ".env")
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    require_local_ingestion(neo4j_uri)

    labels = ("Class", "Document") if args.label == "both" else (args.label.capitalize(),)
    model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    group = None if args.all_groups else (os.getenv("PROJECT_GROUP", "default").strip() or "default")

    driver = GraphDatabase.driver(neo4j_uri, auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password123")))
    try:
        with driver.session() as session:
            hits = query_graph(
                session,
                args.question,
                top_k=args.top,
                project=args.project,
                group=group,
                labels=labels,
                model_name=model_name,
                expand=not args.no_expand,
            )
    finally:
        driver.close()

    if args.json:
        print(json.dumps(hits, indent=2, ensure_ascii=False))
    else:
        print(format_text(args.question, hits))


if __name__ == "__main__":
    main()
