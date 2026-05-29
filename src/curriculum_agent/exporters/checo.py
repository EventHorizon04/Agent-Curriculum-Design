from __future__ import annotations

from curriculum_agent.models import ProgramMetadata, YLOMatrix

# CHECO section mapping:
#   PLO.statement_th     → CHECO 1.6.2 (ผลลัพธ์การเรียนรู้ของหลักสูตร)
#   YLO.statement_th     → CHECO 1.6.3 (ความคาดหวังเมื่อสิ้นปีการศึกษา)
#   ProgramMetadata.program_objectives_th → CHECO 1.5


def export_checo(metadata: ProgramMetadata, matrix: YLOMatrix) -> dict:
    """Return a dict matching CHECO 1.6 structure for serialization to JSON/Word."""
    # TODO: implement full CHECO template population
    raise NotImplementedError
