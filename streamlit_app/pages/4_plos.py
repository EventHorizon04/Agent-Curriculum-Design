from __future__ import annotations

import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

_DOMAIN_LABELS = {"cognitive": "พุทธิพิสัย", "psychomotor": "ทักษะพิสัย", "affective": "จิตพิสัย"}
_BLOOM_LABELS = {
    "remember": "จำ", "understand": "เข้าใจ", "apply": "ประยุกต์",
    "analyze": "วิเคราะห์", "evaluate": "ประเมิน", "create": "สร้าง",
}


def _smart_badge(smart: dict) -> str:
    if all(smart.get(k) for k in ("specific", "measurable", "achievable", "relevant", "timely")):
        return "✅ SMART ผ่าน"
    failed = [k.upper() for k in ("specific", "measurable", "achievable", "relevant", "timely") if not smart.get(k)]
    return f"❌ SMART ไม่ผ่าน ({', '.join(failed)})"


st.title("ขั้นตอนที่ 3 — Program Learning Outcomes (PLO)")
st.info("ตรวจสอบและแก้ไข PLO ก่อนอนุมัติให้ AI สร้าง YLO Matrix")

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
            f"{API_BASE}/programs/{program_id}/plos/",
            timeout=10,
        )
        resp.raise_for_status()
        plos = resp.json()

        if not plos:
            st.warning(
                "ยังไม่มี PLO — ระบบจะสร้างอัตโนมัติหลังจาก Stage 2 สมบูรณ์ "
                "และผู้ออกแบบอนุมัติ skill clusters"
            )
        else:
            st.write(f"พบ **{len(plos)}** PLO")

            for plo in sorted(plos, key=lambda x: x.get("plo_id", "")):
                smart = plo.get("smart_check", {})
                smart_txt = _smart_badge(smart)
                domain_label = _DOMAIN_LABELS.get(plo.get("domain", ""), plo.get("domain", ""))
                bloom_label = _BLOOM_LABELS.get(plo.get("bloom_level", ""), plo.get("bloom_level", ""))

                with st.expander(
                    f"**{plo.get('plo_id', '')}** — {plo.get('statement_th', '')[:60]}... | {smart_txt}"
                ):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**คำอธิบาย:** {plo.get('statement_th', '')}")
                        if plo.get("statement_en"):
                            st.caption(plo["statement_en"])
                        st.write(f"**เหตุผล:** {plo.get('rationale_th', '')}")
                        clusters_ref = ", ".join(plo.get("source_cluster_ids", []))
                        st.write(f"**อ้างอิง clusters:** {clusters_ref or '—'}")
                    with col2:
                        st.write(f"**โดเมน:** {domain_label}")
                        st.write(f"**Bloom:** {bloom_label}")
                        st.write(f"**เวอร์ชัน:** {plo.get('version', 1)}")
                        st.write(f"**Specific:** {'ใช่' if plo.get('is_subject_specific') else 'ไม่'}")

                    st.divider()
                    with st.form(f"edit_plo_{plo.get('plo_id', '')}"):
                        new_statement = st.text_area(
                            "แก้ไข statement (ภาษาไทย)",
                            value=plo.get("statement_th", ""),
                            key=f"stmt_{plo.get('plo_id')}",
                        )
                        save = st.form_submit_button("บันทึกการแก้ไข")

                    if save:
                        updated = {**plo, "statement_th": new_statement}
                        try:
                            put_resp = requests.put(
                                f"{API_BASE}/programs/{program_id}/plos/{plo['plo_id']}",
                                json=updated,
                                timeout=10,
                            )
                            put_resp.raise_for_status()
                            st.success(f"บันทึก {plo['plo_id']} สำเร็จ (version {plo.get('version', 1) + 1})")
                            st.rerun()
                        except requests.exceptions.HTTPError as e:
                            st.error(f"ไม่สามารถบันทึกได้: {e.response.status_code} — {e.response.text}")

    except requests.exceptions.ConnectionError:
        st.error(f"เชื่อมต่อ API ไม่ได้ ({API_BASE})")
    except requests.exceptions.HTTPError as e:
        st.error(f"API error: {e.response.status_code}")

st.divider()
st.caption(f"API: {API_BASE}")
