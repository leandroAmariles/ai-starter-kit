from __future__ import annotations

import sys
from functools import lru_cache

from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=4)
def _load_model(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)


def generate_embedding(text: str, model_name: str = "all-MiniLM-L6-v2") -> list[float]:
    try:
        model = _load_model(model_name)
        return model.encode(text).tolist()
    except Exception as exc:
        message = f"Could not generate embedding with {model_name}: {exc}"
        print(f"ERROR: {message}", file=sys.stderr)
        raise RuntimeError(message) from exc


def validate_embedding_dimension(
    embedding: list[float], expected_dimension: int, subject: str
) -> None:
    if len(embedding) != expected_dimension:
        raise RuntimeError(
            f"Embedding dimension mismatch for {subject}: "
            f"expected {expected_dimension}, got {len(embedding)}"
        )
