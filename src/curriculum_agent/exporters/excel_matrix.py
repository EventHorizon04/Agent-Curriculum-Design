from __future__ import annotations

import io

import pandas as pd

from curriculum_agent.models import YLOMatrix


def export_matrix_xlsx(matrix: YLOMatrix) -> bytes:
    """Export PLO × Year matrix as Excel workbook bytes."""
    rows = []
    for plo in matrix.plos:
        row: dict = {"PLO": plo.plo_id, "ผลลัพธ์การเรียนรู้": plo.statement_th}
        ylos_for_plo = {y.year: y for y in matrix.ylos if y.parent_plo_id == plo.plo_id}
        for year in range(1, 9):
            ylo = ylos_for_plo.get(year)
            row[f"ปีที่ {year}"] = ylo.statement_th if ylo else ""
        rows.append(row)

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()
