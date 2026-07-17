# Design: TOCTOU-safe program_id generation + LLM endpoint rate limiting

**Date:** 2026-07-17
**Status:** Approved
**Scope:** Two deferred follow-up tickets from the intake mko2 work.

## Problem

### 1. TOCTOU race in `_generate_program_id`

`POST /programs/` generates `program_id` by slugifying `name_en`, then loops
`await repo.exists(candidate)` until a free id is found, and finally calls
`repo.upsert(metadata)`. Two concurrent requests with the same `name_en` can
both pass the `exists` check with the same candidate. Because the write path
is an **upsert**, the second request silently overwrites the first program
instead of failing — data loss, not just an id collision.

### 2. No rate limit on LLM-backed endpoints

`POST /programs/extract-metadata` (file parse + light-model call) and
`POST /programs/suggest-isced` (light-model call, up to 2) are the two most
expensive endpoints in the API. Nothing prevents a client from hammering them.

## Design

### 1. INSERT + retry on conflict

- New `ProgramRepository.insert(metadata: ProgramMetadata) -> None`: plain
  INSERT (no existence pre-check). A primary-key conflict on `program_id`
  propagates as `sqlalchemy.exc.IntegrityError`.
- `create_program` route: bounded loop (max 5 attempts). Each attempt runs the
  existing suffix-search (`_generate_program_id`, kept as a fast path) to pick
  a candidate, then calls `repo.insert`. On `IntegrityError` → next attempt
  regenerates. After 5 failed attempts → HTTP 409 with a Thai detail message.
- The database is the arbiter: the check and the write are the same statement,
  so no race window remains. The `exists` loop is only an optimization to find
  a likely-free suffix.
- `ProgramRepository.upsert` is kept unchanged — intake stage 0 uses it
  legitimately (the program row already exists by then).

### 2. In-memory sliding-window rate limiter

- `RateLimiter` class in `src/curriculum_agent/api/deps.py` (same module as
  `require_api_key`):
  - Per-client-IP `deque[float]` of request timestamps.
  - Sliding window: on each request, drop timestamps older than 60 s; if the
    remaining count ≥ limit → raise `HTTPException(429)` with Thai detail and
    a `Retry-After` header (seconds until the oldest timestamp expires).
  - Clock injectable (`time_func` constructor arg, defaults to
    `time.monotonic`) so tests control time.
  - Empty per-IP entries are pruned to bound memory.
  - Client IP from `request.client.host` (no proxy in the PoC deployment).
- Limit configurable via `config.py` pydantic-settings:
  `llm_rate_limit_per_minute: int = 5` (overridable in `.env`, project style).
- Applied as a FastAPI dependency on `/extract-metadata` and `/suggest-isced`
  only. `POST /programs/` is not rate-limited.

**Known limitation (accepted for PoC):** limiter state is per-process — resets
on restart, not shared across workers. Fine for the single-uvicorn deployment.

## Testing

- **TOCTOU (route-level, repo mocked):**
  - `repo.insert` side-effect `[IntegrityError, None]` → response id carries
    a `-2`-style suffix, i.e. the retry regenerated.
  - `IntegrityError` on all 5 attempts → 409.
  - Happy path unchanged: first insert succeeds, id = base slug.
- **Rate limiter (unit, injected clock):**
  - N requests within window pass, N+1 → 429 with `Retry-After`.
  - Advancing the clock past the window frees the slot.
  - Separate IPs tracked independently.
- **Route-level:** hitting `/suggest-isced` beyond the limit → 429 (LLM call
  mocked).

## Out of scope

- Distributed/multi-worker rate limiting (Redis etc.).
- Rate limits on non-LLM endpoints.
- Proxy-aware client IP (X-Forwarded-For).
