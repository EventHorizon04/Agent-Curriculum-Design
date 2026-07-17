from __future__ import annotations

from typing import Any

from curriculum_agent.models import PLO, ProgramMetadata

# CHECO section mapping:
#   PLO.statement_th     → CHECO 1.6.2 (ผลลัพธ์การเรียนรู้ของหลักสูตร)
#   ProgramMetadata.program_objectives_th → CHECO 1.5


def export_checo(metadata: ProgramMetadata, plos: list[PLO]) -> dict[str, Any]:
    """Return a dict matching CHECO 1.6 structure for serialization to JSON/Word."""
    # TODO: implement full CHECO template population
    raise NotImplementedError
