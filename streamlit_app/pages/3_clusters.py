from __future__ import annotations

import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.title("ขั้นตอนที่ 2 — Skill Clusters")
st.info("ตรวจสอบและอนุมัติ skill clusters ก่อนสังเคราะห์ PLO")

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
            f"{API_BASE}/programs/{program_id}/clusters/",
            timeout=10,
        )
        resp.raise_for_status()
        clusters = resp.json()

        if not clusters:
            st.warning(
                "ยังไม่มี skill clusters — ระบบจะสร้างอัตโนมัติหลังจาก Stage 1 สมบูรณ์ "
                "และผู้ออกแบบหลักสูตรอนุมัติหลักฐาน"
            )
        else:
            st.write(f"พบ **{len(clusters)}** clusters")

            _TYPE_LABELS = {
                "knowledge": "ความรู้",
                "psychomotor": "ทักษะปฏิบัติ",
                "affective": "คุณลักษณะ",
                "mixed": "ผสม",
            }

            for c in sorted(clusters, key=lambda x: x.get("demand_score", 0), reverse=True):
                demand = c.get("demand_score", 0)
                is_common = c.get("is_common_need", False)
                badge = "🔴" if demand >= 0.7 else ("🟡" if demand >= 0.4 else "⚪")
                common_tag = " ✅ common need" if is_common else ""
                stype = _TYPE_LABELS.get(c.get("skill_type", ""), c.get("skill_type", ""))

                with st.expander(
                    f"{badge} {c.get('canonical_name_th', '')} ({stype}){common_tag} — demand {demand:.2f}"
                ):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.write(f"**คำอธิบาย:** {c.get('description_th', '')}")
                        quotes = c.get("sample_quotes_th", [])
                        if quotes:
                            st.write("**ตัวอย่างคำพูด:**")
                            for q in quotes[:3]:
                                st.markdown(f"> {q}")
                    with col2:
                        st.metric("Demand Score", f"{demand:.2f}")
                        st.write(f"**สมาชิก:** {len(c.get('member_skill_ids', []))} ทักษะ")
                        st.write(f"**หลักฐาน:** {len(c.get('source_evidence_ids', []))} รายการ")
                        st.write(f"**Specific:** {'ใช่' if c.get('is_subject_specific') else 'ไม่'}")

    except requests.exceptions.ConnectionError:
        st.error(f"เชื่อมต่อ API ไม่ได้ ({API_BASE})")
    except requests.exceptions.HTTPError as e:
        st.error(f"API error: {e.response.status_code}")

st.divider()
st.caption(f"API: {API_BASE}")
