# TOCTOU-safe program_id + LLM Rate Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the TOCTOU race in program_id generation (INSERT + retry, DB as arbiter) and rate-limit the two LLM-backed intake endpoints (in-memory sliding window per IP).

**Architecture:** `ProgramRepository.insert` does a plain INSERT so a duplicate `program_id` raises `IntegrityError`; `create_program` retries id generation up to 5 times before returning 409. A `RateLimiter` class in `api/deps.py` holds per-IP timestamp deques with an injectable clock; a FastAPI dependency applies it to `/extract-metadata` and `/suggest-isced` only.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, pytest (asyncio_mode=auto).

**Spec:** `docs/superpowers/specs/2026-07-17-toctou-ratelimit-design.md`

## Global Constraints

- Python: type hints on every signature, `from __future__ import annotations`.
- Logging via `loguru` only.
- Thai for user-facing strings (HTTP error details); English for code/comments/log messages.
- Do not weaken any Pydantic validators.
- Work on branch `fix/toctou-ratelimit`. Commit after each task.
- Verification commands run from repo root: `uv run pytest -q`, `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run mypy src/` (must stay at 0 errors).

---

### Task 1: TOCTOU — `ProgramRepository.insert` + retry loop in `create_program`

**Files:**
- Modify: `src/curriculum_agent/data/repositories.py` (ProgramRepository, after `upsert`, ~line 58)
- Modify: `src/curriculum_agent/api/routes/programs.py` (`create_program`, lines 46-57)
- Test: `tests/unit/test_api_programs.py`

**Interfaces:**
- Produces: `ProgramRepository.insert(metadata: ProgramMetadata) -> None` — plain INSERT, raises `sqlalchemy.exc.IntegrityError` on `program_id` PK conflict.
- `create_program` behavior change: calls `repo.insert` (not `upsert`); retries up to 5 times; 409 when exhausted.

- [ ] **Step 1: Update existing tests + write new failing tests**

In `tests/unit/test_api_programs.py`:

1. In `test_create_program_generates_slug_id` and `test_create_program_collision_appends_suffix`, replace `mock_repo.upsert = AsyncMock()` with `mock_repo.insert = AsyncMock()`.

2. Add at the top of the file (after existing imports):

```python
from sqlalchemy.exc import IntegrityError
```

3. Append these two tests:

```python
def test_create_program_insert_conflict_retries_with_suffix(monkeypatch) -> None:
    """Concurrent-insert race: exists() said free, but INSERT hits a duplicate
    PK. The route must regenerate (now seeing the winner row) and succeed."""
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        # attempt 1: exists("computer-science") -> False, insert -> conflict
        # attempt 2: exists("computer-science") -> True (winner visible),
        #            exists("computer-science-2") -> False, insert -> ok
        mock_repo.exists = AsyncMock(side_effect=[False, True, False])
        mock_repo.insert = AsyncMock(
            side_effect=[IntegrityError("stmt", {}, Exception("duplicate key")), None]
        )
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    assert resp.json()["program_id"] == "computer-science-2"
    assert mock_repo.insert.await_count == 2


def test_create_program_returns_409_when_attempts_exhausted(monkeypatch) -> None:
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        mock_repo.exists = AsyncMock(return_value=False)
        mock_repo.insert = AsyncMock(
            side_effect=IntegrityError("stmt", {}, Exception("duplicate key"))
        )
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 409, f"got {resp.status_code}: {resp.json()}"
    assert mock_repo.insert.await_count == 5
    mock_graph.ainvoke.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/unit/test_api_programs.py -q`
Expected: the two new tests FAIL (route still calls `upsert`, never `insert`; no retry loop). The two updated tests may also fail — that is fine at this step.

- [ ] **Step 3: Add `ProgramRepository.insert`**

In `src/curriculum_agent/data/repositories.py`, inside `ProgramRepository`, directly after the `upsert` method:

```python
    async def insert(self, metadata: ProgramMetadata) -> None:
        """Plain INSERT — raises IntegrityError if program_id already exists.

        Used by the create route so the database arbitrates concurrent id
        generation. upsert() remains for stage handlers updating an existing
        program.
        """
        async with AsyncSessionLocal() as session:
            data = _fix_datetimes(metadata.model_dump(mode="json"), ProgramTable)
            session.add(ProgramTable(**data))
            await session.commit()
```

- [ ] **Step 4: Rewrite `create_program` with the retry loop**

In `src/curriculum_agent/api/routes/programs.py`:

1. Add import near the other third-party imports:

```python
from sqlalchemy.exc import IntegrityError
```

2. Add a module constant under `_MIN_TEXT_CHARS`:

```python
_MAX_ID_ATTEMPTS = 5
```

3. Replace the body of `create_program`:

```python
@router.post("/", response_model=ProgramMetadata, dependencies=[Depends(require_api_key)])
async def create_program(req: ProgramCreateRequest, request: Request) -> ProgramMetadata:
    repo = ProgramRepository()
    metadata: ProgramMetadata | None = None
    for _ in range(_MAX_ID_ATTEMPTS):
        program_id = await _generate_program_id(req.name_en, repo)
        candidate = ProgramMetadata(program_id=program_id, **req.model_dump())
        try:
            await repo.insert(candidate)
        except IntegrityError:
            # Lost a concurrent-create race; the next _generate_program_id
            # call sees the winner's row and picks the next suffix.
            logger.warning(f"program_id '{program_id}' taken concurrently, retrying")
            continue
        metadata = candidate
        break
    if metadata is None:
        raise HTTPException(
            status_code=409, detail="สร้างรหัสหลักสูตรไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"
        )
    graph = request.app.state.graph
    await graph.ainvoke(
        {"program_id": metadata.program_id, "metadata": metadata.model_dump(mode="json")},
        config={"configurable": {"thread_id": metadata.program_id}},
    )
    return metadata
```

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest tests/unit/test_api_programs.py -q`
Expected: all pass.

- [ ] **Step 6: Full verification**

Run: `uv run pytest -q` → all pass (~152 tests).
Run: `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/` → all clean.

- [ ] **Step 7: Commit**

```bash
git add src/curriculum_agent/data/repositories.py src/curriculum_agent/api/routes/programs.py tests/unit/test_api_programs.py
git commit -m "fix(api): close TOCTOU race in program_id generation with INSERT + retry"
```

---

### Task 2: In-memory sliding-window rate limiter on LLM endpoints

**Files:**
- Modify: `src/curriculum_agent/config.py` (Settings fields, ~line 22)
- Modify: `src/curriculum_agent/api/deps.py` (append)
- Modify: `src/curriculum_agent/api/routes/programs.py` (`dependencies=` on 2 routes)
- Test: `tests/unit/test_rate_limit.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `RateLimiter(limit: int, window_seconds: float = 60.0, time_func: Callable[[], float] = time.monotonic)` with method `check(client_ip: str) -> None` (raises `HTTPException` 429); module-level instance `llm_rate_limiter`; async dependency `enforce_llm_rate_limit(request: Request) -> None`; settings field `llm_rate_limit_per_minute: int = 5`.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_rate_limit.py`:

```python
# tests/unit/test_rate_limit.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from curriculum_agent.api.deps import RateLimiter
from curriculum_agent.api.main import app
from curriculum_agent.models import IscedSuggestion, SuggestedName

client = TestClient(app)


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# --- RateLimiter unit ---


def test_allows_requests_up_to_limit() -> None:
    limiter = RateLimiter(limit=3, time_func=FakeClock())
    for _ in range(3):
        limiter.check("1.2.3.4")  # must not raise


def test_blocks_over_limit_with_retry_after() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=2, time_func=clock)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("1.2.3.4")
    assert exc_info.value.status_code == 429
    assert int(exc_info.value.headers["Retry-After"]) >= 1


def test_window_slides_frees_slot() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=1, window_seconds=60.0, time_func=clock)
    limiter.check("1.2.3.4")
    clock.advance(61.0)
    limiter.check("1.2.3.4")  # must not raise


def test_ips_tracked_independently() -> None:
    limiter = RateLimiter(limit=1, time_func=FakeClock())
    limiter.check("1.2.3.4")
    limiter.check("5.6.7.8")  # must not raise


# --- route wiring ---

_SUGGESTION = IscedSuggestion(
    isced_code="0613",
    field_name_en="Software and applications development and analysis",
    field_name_th="การพัฒนาและวิเคราะห์ซอฟต์แวร์และแอปพลิเคชัน",
    rationale_th="เหตุผลทดสอบ",
    suggested_names=[SuggestedName(name_th="วิทยาการคอมพิวเตอร์", name_en="Computer Science")],
)

_REQ = {"name_th": "วิทยาการคอมพิวเตอร์", "name_en": "Computer Science", "field": "CS"}


def test_suggest_isced_returns_429_over_limit(monkeypatch) -> None:
    import curriculum_agent.api.deps as deps

    monkeypatch.setattr(deps, "llm_rate_limiter", RateLimiter(limit=1))
    with patch(
        "curriculum_agent.api.routes.programs.suggest_isced",
        new=AsyncMock(return_value=_SUGGESTION),
    ):
        first = client.post("/programs/suggest-isced", json=_REQ)
        second = client.post("/programs/suggest-isced", json=_REQ)
    assert first.status_code == 200, f"got {first.status_code}: {first.json()}"
    assert second.status_code == 429, f"got {second.status_code}: {second.json()}"
    assert "Retry-After" in second.headers


def test_extract_metadata_shares_the_limiter(monkeypatch) -> None:
    """Both LLM endpoints sit behind the same limiter instance."""
    import curriculum_agent.api.deps as deps

    monkeypatch.setattr(deps, "llm_rate_limiter", RateLimiter(limit=1))
    with patch(
        "curriculum_agent.api.routes.programs.suggest_isced",
        new=AsyncMock(return_value=_SUGGESTION),
    ):
        first = client.post("/programs/suggest-isced", json=_REQ)
    second = client.post(
        "/programs/extract-metadata",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/octet-stream")},
    )
    assert first.status_code == 200
    assert second.status_code == 429, f"got {second.status_code}: {second.json()}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_rate_limit.py -q`
Expected: FAIL at import — `ImportError: cannot import name 'RateLimiter'`.

- [ ] **Step 3: Add the settings field**

In `src/curriculum_agent/config.py`, after `api_key: str | None = None`:

```python
    llm_rate_limit_per_minute: int = 5
```

- [ ] **Step 4: Implement `RateLimiter` + dependency in deps.py**

In `src/curriculum_agent/api/deps.py`:

1. Update imports (top of file):

```python
from __future__ import annotations

import time
from collections import deque
from collections.abc import AsyncGenerator, Callable

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from curriculum_agent.config import settings
from curriculum_agent.data.postgres import AsyncSessionLocal
```

2. Append at the end of the file:

```python
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
```

Note: `enforce_llm_rate_limit` reads the module global at call time, so tests can swap `deps.llm_rate_limiter` with monkeypatch.

- [ ] **Step 5: Wire the dependency onto both routes**

In `src/curriculum_agent/api/routes/programs.py`:

1. Update the deps import:

```python
from curriculum_agent.api.deps import enforce_llm_rate_limit, require_api_key
```

2. On the `/extract-metadata` route decorator, change `dependencies=`:

```python
@router.post(
    "/extract-metadata",
    response_model=ExtractedMetadata,
    dependencies=[Depends(require_api_key), Depends(enforce_llm_rate_limit)],
)
```

3. Same change on `/suggest-isced`:

```python
@router.post(
    "/suggest-isced",
    response_model=IscedSuggestion,
    dependencies=[Depends(require_api_key), Depends(enforce_llm_rate_limit)],
)
```

- [ ] **Step 6: Run the new tests**

Run: `uv run pytest tests/unit/test_rate_limit.py -q`
Expected: all 6 pass.

- [ ] **Step 7: Full verification**

Run: `uv run pytest -q` → all pass. Note: `tests/unit/test_extract_metadata.py` sends multiple requests from the same TestClient IP; the default limit is 5/min, and that file has 9 route tests — if any fail with 429, add an autouse fixture to `tests/unit/test_extract_metadata.py`:

```python
import pytest

from curriculum_agent.api.deps import RateLimiter


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    import curriculum_agent.api.deps as deps

    monkeypatch.setattr(deps, "llm_rate_limiter", RateLimiter(limit=1_000_000))
```

Run: `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/` → all clean.

- [ ] **Step 8: Commit**

```bash
git add src/curriculum_agent/config.py src/curriculum_agent/api/deps.py src/curriculum_agent/api/routes/programs.py tests/unit/test_rate_limit.py tests/unit/test_extract_metadata.py
git commit -m "feat(api): per-IP sliding-window rate limit on LLM intake endpoints"
```
