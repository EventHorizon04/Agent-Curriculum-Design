from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

BGE_MODEL_ID = "BAAI/bge-m3"


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(BGE_MODEL_ID)


def embed(texts: list[str]) -> list[list[float]]:
    model = get_model()
    return model.encode(texts, normalize_embeddings=True).tolist()
