from __future__ import annotations

from qdrant_client import AsyncQdrantClient

from curriculum_agent.config import settings

_client: AsyncQdrantClient | None = None


def get_qdrant() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url)
    return _client


EVIDENCE_COLLECTION = "evidence"
SKILL_COLLECTION = "skills"
