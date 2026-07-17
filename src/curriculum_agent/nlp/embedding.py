from __future__ import annotations

from functools import lru_cache
from logging import getLogger
from typing import cast

import torch
from sentence_transformers import SentenceTransformer

logger = getLogger(__name__)

BGE_MODEL_ID = "BAAI/bge-m3"


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    logger.info("Loading embedding model...")
    return cast(
        SentenceTransformer,
        SentenceTransformer(
            BGE_MODEL_ID, device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
        ),
    )


def embed(texts: list[str]) -> list[list[float]]:
    model = get_model()
    return model.encode(texts, normalize_embeddings=True).tolist()
