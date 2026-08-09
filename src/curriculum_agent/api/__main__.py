"""Entrypoint that gives uvicorn an event loop psycopg can work with.

`uvicorn curriculum_agent.api.main:app` picks its loop from
`Config.get_loop_factory()`, which on Windows returns `ProactorEventLoop` unless
`use_subprocess` (reload, or workers > 1) is set — and psycopg refuses that loop.
`--reload` is what has been hiding this: it flips `use_subprocess` on, which is
the only reason the dev script has worked. Setting an event loop *policy* does
not help, because uvicorn never reads one; it passes the factory straight to
`asyncio.Runner`. So name the factory, which `Config.get_loop_factory()` accepts
as a "module:attr" string.

Run the API through this module:

    uv run python -m curriculum_agent.api

Host, port, and reload come from API_HOST / API_PORT / API_RELOAD.
"""

from __future__ import annotations

import os
import sys

import uvicorn

# "auto" elsewhere so uvloop still wins on Linux, where the problem doesn't exist.
_LOOP = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"


def main() -> None:
    uvicorn.run(
        "curriculum_agent.api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=os.getenv("API_RELOAD", "").lower() in {"1", "true", "yes"},
        loop=_LOOP,
    )


if __name__ == "__main__":
    main()
