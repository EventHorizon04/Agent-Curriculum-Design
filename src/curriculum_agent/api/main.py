from __future__ import annotations

from fastapi import FastAPI

from curriculum_agent.api.routes import clusters, evidence, plos, programs, ylos

app = FastAPI(title="Curriculum Design Agent", version="0.1.0")

app.include_router(programs.router, prefix="/programs", tags=["programs"])
app.include_router(evidence.router, prefix="/programs/{program_id}/evidence", tags=["evidence"])
app.include_router(clusters.router, prefix="/programs/{program_id}/clusters", tags=["clusters"])
app.include_router(plos.router, prefix="/programs/{program_id}/plos", tags=["plos"])
app.include_router(ylos.router, prefix="/programs/{program_id}/ylos", tags=["ylos"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
