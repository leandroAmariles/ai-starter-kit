from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

GRAPH_RAG_DIR = Path(__file__).resolve().parents[1]
if str(GRAPH_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(GRAPH_RAG_DIR))

from ingestion.maven_coordinates import parse_pom, read_project_coordinates
from ingestion.parsers.generic_file_parser import (
    MAX_CONTENT_BYTES,
    extract_local_references,
    parse_generic_file,
)
from ingestion.embedder import generate_embedding, validate_embedding_dimension
from ingestion import phase1_scan, phase2_embed_ingest
from ingestion.neo4j_safety import require_local_ingestion
from ingestion.phase1_scan import parse_project_paths
from ingestion.phase2_embed_ingest import validate_summaries
from ingestion.scanner import (
    compare_inventory,
    scan_documents,
    scan_repo,
    tracked_inventory,
)


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)


class ScannerTest(unittest.TestCase):
    def test_scanners_partition_a_repository_git_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "src").mkdir()
            (root / "src" / "Foo.java").write_text("class Foo {}", encoding="utf-8")
            (root / "README.md").write_text("# Test repo", encoding="utf-8")
            _init_git_repo(root)

            expected = {
                path
                for path in subprocess.run(
                    ["git", "-C", str(root), "ls-files", "--cached"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines()
                if (root / path).is_file()
            }
            code_paths = {p.relative_to(root).as_posix() for p in scan_repo(str(root))}
            document_paths = {p.relative_to(root).as_posix() for p in scan_documents(str(root))}

            self.assertEqual(expected, code_paths | document_paths)
            self.assertFalse(code_paths & document_paths)
            self.assertEqual({"src/Foo.java"}, code_paths)

    def test_document_references_only_include_existing_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "docs.md").write_text("See [guide](README.md) and [gone](missing.md).", encoding="utf-8")
            (root / "README.md").write_text("# Readme", encoding="utf-8")
            _init_git_repo(root)

            known_paths = {
                p.relative_to(root).as_posix()
                for p in [*scan_repo(str(root)), *scan_documents(str(root))]
            }
            document_path = root / "docs.md"
            references = extract_local_references(
                document_path, document_path.read_text(encoding="utf-8"), root, known_paths
            )

            self.assertIn("README.md", references)
            self.assertNotIn("missing.md", references)
            self.assertTrue(references.issubset(known_paths))

    def test_inventory_hash_detects_worktree_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "README.md").write_text("# Readme", encoding="utf-8")
            _init_git_repo(root)

            metadata = tracked_inventory(str(root))
            expected = {"README.md": metadata["README.md"]}
            indexed_node = {**metadata["README.md"], "content_hash": "outdated-blob"}

            missing, stale, modified = compare_inventory(expected, {"README.md": [indexed_node]})

            self.assertEqual(set(), missing)
            self.assertEqual(set(), stale)
            self.assertEqual({"README.md": ["content_hash"]}, modified)

    def test_inventory_reports_missing_stale_and_parser_version_changes(self) -> None:
        expected = {
            "missing.java": {
                "node_label": "Class",
                "content_hash": "a",
                "parser_version": "java-v2",
                "schema_version": "3",
            },
            "changed.md": {
                "node_label": "Document",
                "content_hash": "b",
                "parser_version": "generic-v2",
                "schema_version": "3",
            },
        }
        indexed = {
            "changed.md": [{
                "node_label": "Document",
                "content_hash": "b",
                "parser_version": "generic-v1",
                "schema_version": "3",
            }],
            "removed.yml": [{
                "node_label": "Document",
                "content_hash": "c",
                "parser_version": "generic-v2",
                "schema_version": "3",
            }],
        }

        missing, stale, modified = compare_inventory(expected, indexed)

        self.assertEqual({"missing.java"}, missing)
        self.assertEqual({"removed.yml"}, stale)
        self.assertEqual({"changed.md": ["parser_version"]}, modified)

    def test_generic_parser_reads_at_most_the_configured_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_stream = mock_open(read_data=b"a" * (MAX_CONTENT_BYTES + 1))
            with patch.object(Path, "open", file_stream):
                parsed = parse_generic_file(str(root / "large.txt"), root)

            file_stream().read.assert_called_once_with(MAX_CONTENT_BYTES + 1)
            self.assertTrue(parsed["truncated"])
            self.assertEqual(MAX_CONTENT_BYTES, len(parsed["content"]))


class MultiProjectConfigTest(unittest.TestCase):
    def test_parses_bare_paths_defaulting_name_to_directory_basename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp).resolve()
            (host_root / "orders").mkdir()
            graph_rag_dir = host_root / "graph-rag"
            graph_rag_dir.mkdir()

            entries = parse_project_paths("./orders", graph_rag_dir)

            self.assertEqual([("orders", host_root / "orders")], entries)

    def test_parses_explicit_name_equals_path_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp).resolve()
            (host_root / "payments").mkdir()
            graph_rag_dir = host_root / "graph-rag"
            graph_rag_dir.mkdir()

            entries = parse_project_paths(
                "orders=.,payments=./payments", graph_rag_dir
            )

            self.assertEqual(
                [("orders", host_root), ("payments", host_root / "payments")], entries
            )

    def test_rejects_duplicate_project_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_rag_dir = Path(tmp) / "graph-rag"
            graph_rag_dir.mkdir(parents=True)

            with self.assertRaises(SystemExit):
                parse_project_paths("a=.,a=.", graph_rag_dir)

    def test_rejects_empty_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_rag_dir = Path(tmp) / "graph-rag"
            graph_rag_dir.mkdir(parents=True)

            with self.assertRaises(SystemExit):
                parse_project_paths("  , ,", graph_rag_dir)


class MavenCoordinatesTest(unittest.TestCase):
    POM_TEMPLATE = """<project>
      <groupId>{group}</groupId>
      <artifactId>{artifact}</artifactId>
      <dependencies>
        <dependency>
          <groupId>{dep_group}</groupId>
          <artifactId>{dep_artifact}</artifactId>
        </dependency>
      </dependencies>
    </project>"""

    def test_reads_own_coordinate_and_dependency_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pom = root / "pom.xml"
            pom.write_text(
                self.POM_TEMPLATE.format(
                    group="com.acme", artifact="orders-service",
                    dep_group="com.acme", dep_artifact="shared-lib",
                ),
                encoding="utf-8",
            )

            provided, required = parse_pom(pom)

            self.assertEqual(("com.acme", "orders-service"), provided)
            self.assertEqual({("com.acme", "shared-lib")}, required)

    def test_cross_project_dependency_is_detected_via_matching_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orders_root = Path(tmp) / "orders"
            shared_root = Path(tmp) / "shared-lib"
            orders_root.mkdir()
            shared_root.mkdir()

            (orders_root / "pom.xml").write_text(
                self.POM_TEMPLATE.format(
                    group="com.acme", artifact="orders-service",
                    dep_group="com.acme", dep_artifact="shared-lib",
                ),
                encoding="utf-8",
            )
            (shared_root / "pom.xml").write_text(
                self.POM_TEMPLATE.format(
                    group="com.acme", artifact="shared-lib",
                    dep_group="org.springframework", dep_artifact="spring-core",
                ),
                encoding="utf-8",
            )

            orders_provided, orders_required = read_project_coordinates(
                orders_root, ["pom.xml"]
            )
            shared_provided, _ = read_project_coordinates(shared_root, ["pom.xml"])

            self.assertEqual({("com.acme", "orders-service")}, orders_provided)
            self.assertTrue(orders_required & shared_provided)

    def test_returns_nothing_for_a_malformed_pom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pom = Path(tmp) / "pom.xml"
            pom.write_text("not xml", encoding="utf-8")

            provided, required = parse_pom(pom)

            self.assertIsNone(provided)
            self.assertEqual(set(), required)


class SafetyAndEmbeddingTest(unittest.TestCase):
    def test_ingestion_accepts_only_loopback_neo4j_uris(self) -> None:
        for uri in (
            "bolt://localhost:7687",
            "neo4j://127.0.0.1:7687",
            "bolt://[::1]:7687",
        ):
            require_local_ingestion(uri)

        for uri in (
            "bolt://neo4j.internal:7687",
            "neo4j+s://database.example.com",
            "localhost:7687",
        ):
            with self.assertRaises(RuntimeError):
                require_local_ingestion(uri)

    def test_normal_phase1_refuses_remote_uri_before_creating_driver(self) -> None:
        with (
            patch.dict(os.environ, {"NEO4J_URI": "bolt://shared.example.com:7687"}),
            patch.object(sys, "argv", ["phase1_scan.py"]),
            patch.object(phase1_scan, "GraphIngestor") as ingestor_constructor,
        ):
            with self.assertRaisesRegex(RuntimeError, "non-local Neo4j URI"):
                phase1_scan.main()

        ingestor_constructor.assert_not_called()

    def test_phase2_refuses_remote_uri_before_creating_driver(self) -> None:
        with (
            patch.dict(os.environ, {"NEO4J_URI": "neo4j+s://shared.example.com"}),
            patch.object(phase2_embed_ingest, "GraphIngestor") as ingestor_constructor,
        ):
            with self.assertRaisesRegex(RuntimeError, "non-local Neo4j URI"):
                phase2_embed_ingest.main()

        ingestor_constructor.assert_not_called()

    def test_summary_validation_rejects_unknown_duplicate_and_missing_fqns(self) -> None:
        extracted = [{"fqn": "a.A"}, {"fqn": "b.B"}]
        summaries = [
            {"fqn": "a.A", "summary": "A"},
            {"fqn": "a.A", "summary": "Duplicate"},
            {"fqn": "c.C", "summary": "Unknown"},
        ]

        with self.assertRaisesRegex(
            ValueError, "duplicate FQNs.*unknown FQNs.*missing FQNs"
        ):
            validate_summaries(summaries, extracted)

    def test_summary_validation_accepts_exact_inventory(self) -> None:
        summaries = [
            {"fqn": "a.A", "summary": "Summary A"},
            {"fqn": "b.B", "summary": "Summary B"},
        ]

        self.assertEqual(
            summaries,
            validate_summaries(summaries, [{"fqn": "a.A"}, {"fqn": "b.B"}]),
        )

    def test_embedding_generation_and_dimension_errors_fail(self) -> None:
        with patch(
            "ingestion.embedder._load_model",
            side_effect=RuntimeError("model unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "model unavailable"):
                generate_embedding("text")

        with self.assertRaisesRegex(RuntimeError, "expected 384, got 2"):
            validate_embedding_dimension([0.1, 0.2], 384, "test")


if __name__ == "__main__":
    unittest.main()
