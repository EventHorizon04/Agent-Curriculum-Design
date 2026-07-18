from __future__ import annotations

import time
from collections import deque
from collections.abc import AsyncGenerator, Callable

from fastapi import HTTPException, Request, Security, status
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
            detail="API key ไม่ถูกต้องหรือไม่ได้ระบุ",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key


class RateLimiter:
    """Sliding-window per-IP rate limiter.

    In-process state only: resets on restart and is not shared between
    workers — accepted for the single-uvicorn PoC deployment.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._now = time_func
        self._hits: dict[str, deque[float]] = {}
        self._checks = 0

    def check(self, client_ip: str) -> None:
        """Record a hit for client_ip, or raise HTTP 429 if over the limit."""
        now = self._now()
        self._checks += 1
        if self._checks % 256 == 0:
            self._prune(now)
        hits = self._hits.setdefault(client_ip, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            retry_after = max(1, int(self._window - (now - hits[0])) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="เรียกใช้บ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)

    def _prune(self, now: float) -> None:
        stale = [ip for ip, dq in self._hits.items() if not dq or now - dq[-1] >= self._window]
        for ip in stale:
            del self._hits[ip]


llm_rate_limiter = RateLimiter(limit=settings.llm_rate_limit_per_minute)


async def enforce_llm_rate_limit(request: Request) -> None:
    """Per-IP rate limit for the LLM-backed intake endpoints."""
    client_ip = request.client.host if request.client else "unknown"
    llm_rate_limiter.check(client_ip)
