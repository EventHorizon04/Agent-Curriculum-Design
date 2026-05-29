from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

_BLOOM_LABELS = {
    "remember": "จำ", "understand": "เข้าใจ", "apply": "ประยุกต์",
    "analyze": "วิเคราะห์", "evaluate": "ประเมิน", "create": "สร้าง",
}

st.title("ขั้นตอนที่ 4 — Year Learning Outcomes (YLO) Matrix")
st.info("ตรวจสอบตาราง PLO × ปี และดาวน์โหลดรายงาน")

program_id = st.session_state.get("program_id", "")
if not program_id:
    st.warning("กรุณาเลือกหรือสร้างหลักสูตรในหน้าที่ 1 ก่อน")
    program_id = st.text_input("หรือระบุรหัสหลักสูตรที่นี่")
    if program_id:
        st.session_state["program_id"] = program_id

if program_id:
    st.info(f"หลักสูตร: **{program_id}**")

    try:
        resp = requests.get(
            f"{API_BASE}/programs/{program_id}/ylos/matrix",
            timeout=10,
        )

        if resp.status_code == 404:
            st.warning(
                "ยังไม่มี YLO Matrix — ระบบจะสร้างอัตโนมัติหลังจาก Stage 3 สมบูรณ์ "
                "และผู้ออกแบบอนุมัติ PLO ทั้งหมด"
            )
        else:
            resp.raise_for_status()
            data = resp.json()
            plos = data.get("plos", [])
            ylos = data.get("ylos", [])

            if not plos:
                st.warning("ยังไม่มี PLO ใน matrix")
            else:
                st.write(f"**{len(plos)} PLO** × **{data.get('duration_years', 4)} ปี**")

                # Build matrix table
                years = sorted({y["year"] for y in ylos}) if ylos else list(range(1, 5))
                rows = []
                for plo in sorted(plos, key=lambda x: x.get("plo_id", "")):
                    plo_ylos = {y["year"]: y for y in ylos if y.get("parent_plo_id") == plo["plo_id"]}
                    row: dict = {
                        "PLO": plo["plo_id"],
                        "ผลลัพธ์การเรียนรู้": plo.get("statement_th", ""),
                    }
                    for yr in years:
                        ylo = plo_ylos.get(yr)
                        if ylo:
                            bloom = _BLOOM_LABELS.get(ylo.get("bloom_level", ""), ylo.get("bloom_level", ""))
                            row[f"ปีที่ {yr}"] = f"[{bloom}] {ylo.get('statement_th', '')}"
                        else:
                            row[f"ปีที่ {yr}"] = ""
                    rows.append(row)

                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)

                # Coverage validation
                st.subheader("การตรวจสอบ Coverage")
                from curriculum_agent.models import YLOMatrix as _Matrix
                try:
                    matrix_obj = _Matrix.model_validate(data)
                    issues = matrix_obj.validate_coverage()
                    if issues:
                        for issue in issues:
                            st.warning(f"⚠️ {issue}")
                    else:
                        st.success("✅ Coverage ผ่านทุกเงื่อนไข")
                except Exception as ve:
                    st.error(f"ไม่สามารถตรวจสอบ coverage ได้: {ve}")

                # Export section
                st.subheader("ดาวน์โหลด")
                col1, col2 = st.columns(2)

                with col1:
                    import io
                    buf = io.BytesIO()
                    df.to_excel(buf, index=False)
                    st.download_button(
                        "📥 ดาวน์โหลด Excel",
                        data=buf.getvalue(),
                        file_name=f"ylo_matrix_{program_id}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

                with col2:
                    import json
                    st.download_button(
                        "📥 ดาวน์โหลด JSON (CHECO)",
                        data=json.dumps(data, ensure_ascii=False, indent=2),
                        file_name=f"ylo_matrix_{program_id}.json",
                        mime="application/json",
                    )

    except requests.exceptions.ConnectionError:
        st.error(f"เชื่อมต่อ API ไม่ได้ ({API_BASE})")
    except requests.exceptions.HTTPError as e:
        st.error(f"API error: {e.response.status_code}")

st.divider()
st.caption(f"API: {API_BASE}")
