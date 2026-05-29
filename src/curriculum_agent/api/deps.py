from __future__ import annotations

from typing import AsyncGenerator

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from curriculum_agent.config import settings
from curriculum_agent.data.postgres import AsyncSessionLocal

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def require_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    """Require X-API-Key header. If settings.api_key is None, auth is disabled (dev mode)."""
    if not settings.api_key:
        return "no-auth-configured"
    if api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
