"""Serve the built React bundle from the API process, on one origin.

Mounting at "/" makes StaticFiles the handler for every path the routers did
not claim, which is what a BrowserRouter app needs: `/plo-report` has no file
behind it and must still return the app shell so a reload works. The exception
is anything under an API prefix — a mistyped `/programs/...` path has to stay a
JSON 404, because answering it with HTML turns a backend error into a blank
screen with a 200 next to it in the network tab.

A `Mount("/")` matches every path, so Starlette's router never reaches its
`redirect_slashes` branch — that branch only runs when no route (and no mount)
claims the raw path. Concretely: `GET /programs` 307-redirects to
`/programs/` when this module is not mounted, and 404s once it is. Client code
must therefore call routes with the exact path the decorator declares —
collection routes ending in `@router.post("/")` / `@router.get("/")` really
live at `.../<prefix>/` with the trailing slash, and a call that omits it is a
latent bug that only worked by accident of the redirect. The same absence of
routing fallthrough means a method mismatch on an API path (e.g. `DELETE` on a
path that only defines `GET`) now surfaces as 404 rather than FastAPI's usual
405, since the "no route matched" case and the "wrong method" case both fall
through to this mount's catch-all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

# First path segments owned by the API. Kept here rather than derived from
# app.routes so the rule is readable and a new router cannot silently start
# swallowing a client route.
API_PREFIXES: frozenset[str] = frozenset({"programs", "health", "docs", "redoc", "openapi.json"})


class _SPAStaticFiles(StaticFiles):
    """StaticFiles that answers unknown non-API paths with index.html."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            # Normalize path separators (get_path runs os.path.normpath, which
            # on Windows returns backslash-joined segments) and take the first
            # segment. get_path never yields a leading separator, so no lstrip.
            normalized = path.replace("\\", "/")
            first_segment = normalized.split("/", 1)[0]
            if first_segment in API_PREFIXES:
                raise
            return await super().get_response("index.html", scope)


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Mount `dist` at "/". Call after every include_router.

    Raises RuntimeError when the bundle is absent: a missing build is a
    deployment mistake worth failing on at startup, not a 404 per request that
    looks like a routing bug.
    """
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError(
            f"Frontend bundle not found at {dist}. Run `npm run build` in "
            "frontend/, or set SERVE_FRONTEND=false."
        )
    static: Any = _SPAStaticFiles(directory=dist, html=True)
    app.mount("/", static, name="frontend")
