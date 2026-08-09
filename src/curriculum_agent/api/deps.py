from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator

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
    """Require X-API-Key header. If settings.api_key is unset or blank, auth is
    disabled (dev mode)."""
    if not settings.api_key:
        return "no-auth-configured"
    expected = settings.api_key.get_secret_value()
    # compare_digest over bytes, not `!=` over str: the naive comparison returns
    # as soon as two characters differ, which leaks the length of the matching
    # prefix to anyone timing the responses. Bytes because compare_digest refuses
    # non-ASCII str outright.
    if api_key is None or not secrets.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key ไม่ถูกต้องหรือไม่ได้ระบุ",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
