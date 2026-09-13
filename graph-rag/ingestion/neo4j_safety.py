from __future__ import annotations

from urllib.parse import urlparse

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def require_local_ingestion(uri: str) -> None:
    """Refuse repository ingestion unless Neo4j is configured on loopback."""
    if urlparse(uri).hostname not in LOOPBACK_HOSTS:
        raise RuntimeError(
            f"Refusing Graph RAG ingestion for non-local Neo4j URI: {uri}"
        )
