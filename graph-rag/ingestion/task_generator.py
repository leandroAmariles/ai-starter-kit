from __future__ import annotations

import json
import sys
from pathlib import Path


def _escape(value: object) -> str:
    text = str(value)
    return text.replace("|", "\\|")


def generate_pipeline_tasks(extracted_classes_path: str, output_path: str) -> None:
    extracted_path = Path(extracted_classes_path)
    output_file = Path(output_path)
    classes = json.loads(extracted_path.read_text(encoding="utf-8"))
    venv_python = ".venv\\Scripts\\python.exe" if sys.platform == "win32" else ".venv/bin/python"

    rows = []
    for item in classes:
        annotations = ", ".join(item.get("annotations", []))
        implements = ", ".join(item.get("implements", []))
        rows.append(
            f"| {_escape(item.get('fqn', ''))} | {_escape(item.get('type', ''))} | "
            f"{_escape(annotations)} | {_escape(implements)} |"
        )

    content = "\n".join(
        [
            "# Graph RAG Pipeline — Tasks for LLM Execution",
            "",
            "This file was auto-generated. Execute each step in order.",
            "",
            "## Step 1 — Extract AST and ingest graph [type: shell] ✅ ALREADY DONE",
            "This step was completed by phase1_scan.py. Data is in data/extracted_classes.json.",
            "",
            "## Step 2 — Generate summaries [type: llm]",
            "",
            "Read the class list below. For EACH class, write a 2-3 sentence summary describing:",
            "1. Its role in hexagonal architecture (domain entity, use case, inbound adapter, outbound adapter, port, configuration, etc.)",
            "2. What it does and what it depends on.",
            "",
            "Output ONLY valid JSON to the file `data/summaries.json` in this exact format:",
            "[",
            '  {"fqn": "com.example.MyClass", "summary": "..."},',
            "  ...",
            "]",
            "",
            f"### Classes to summarize ({len(classes)} total):",
            "",
            "| fqn | type | annotations | implements |",
            "|-----|------|-------------|------------|",
            *rows,
            "",
            "## Step 3 — Embed and ingest summaries [type: shell]",
            f"Run: `{venv_python} ingestion/phase2_embed_ingest.py`",
            "Expected: All Class nodes in Neo4j updated with embedding and summary properties.",
            "",
        ]
    )

    output_file.write_text(content, encoding="utf-8")
