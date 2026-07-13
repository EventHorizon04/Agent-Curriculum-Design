from __future__ import annotations

import io

import pandas as pd

from curriculum_agent.models import PLO


def export_matrix_xlsx(plos: list[PLO]) -> bytes:
    """Export PLO list as Excel workbook bytes."""
    rows = [{"PLO": plo.plo_id, "ผลลัพธ์การเรียนรู้": plo.statement_th} for plo in plos]

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()
