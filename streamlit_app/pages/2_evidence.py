from __future__ import annotations

import os
import uuid

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.title("ขั้นตอนที่ 1 — หลักฐานผู้มีส่วนได้ส่วนเสีย")

program_id = st.session_state.get("program_id", "")
if not program_id:
    st.warning("กรุณาเลือกหรือสร้างหลักสูตรในหน้าที่ 1 ก่อน")
    program_id = st.text_input("หรือระบุรหัสหลักสูตรที่นี่")
    if program_id:
        st.session_state["program_id"] = program_id

if program_id:
    st.info(f"หลักสูตร: **{program_id}**")

    st.subheader("เพิ่มหลักฐานใหม่")
    with st.form("add_evidence_form"):
        stakeholder_type = st.selectbox(
            "ประเภทผู้มีส่วนได้ส่วนเสีย",
            ["employer", "alumni", "faculty", "student", "industry_expert", "accreditor"],
        )
        source_name = st.text_input("แหล่งที่มา *", placeholder="บริษัท ABC / ผู้ประกอบการ XYZ")
        raw_text = st.text_area(
            "ข้อความหลักฐาน (ภาษาไทย) *",
            height=150,
            placeholder="วางข้อความที่ได้จากการสัมภาษณ์ แบบสอบถาม หรือเอกสาร...",
        )
        add_submitted = st.form_submit_button("เพิ่มหลักฐาน")

    if add_submitted:
        if not (source_name and raw_text):
            st.error("กรุณากรอกแหล่งที่มาและข้อความหลักฐาน")
        else:
            payload = {
                "evidence_id": str(uuid.uuid4()),
                "program_id": program_id,
                "stakeholder_type": stakeholder_type,
                "source_name": source_name,
                "raw_text_th": raw_text,
            }
            try:
                resp = requests.post(
                    f"{API_BASE}/programs/{program_id}/evidence/",
                    json=payload,
                    timeout=15,
                )
                resp.raise_for_status()
                st.success("เพิ่มหลักฐานสำเร็จ")
                st.rerun()
            except requests.exceptions.ConnectionError:
                st.error(f"เชื่อมต่อ API ไม่ได้ ({API_BASE})")
            except requests.exceptions.HTTPError as e:
                st.error(f"API error: {e.response.status_code} — {e.response.text}")

    st.divider()
    st.subheader("หลักฐานทั้งหมด")

    try:
        resp = requests.get(
            f"{API_BASE}/programs/{program_id}/evidence/",
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json()

        if not items:
            st.caption("ยังไม่มีหลักฐาน — เพิ่มหลักฐานด้านบน")
        else:
            st.write(f"พบ **{len(items)}** รายการ")
            _TYPE_LABELS = {
                "employer": "นายจ้าง",
                "alumni": "ศิษย์เก่า",
                "faculty": "อาจารย์",
                "student": "นักศึกษา",
                "industry_expert": "ผู้เชี่ยวชาญ",
                "accreditor": "ผู้ประเมิน",
            }
            for item in items:
                label = _TYPE_LABELS.get(item.get("stakeholder_type", ""), item.get("stakeholder_type", ""))
                cls = item.get("classification", "unclassified")
                badge = {"need": "🟢", "requirement": "🔵", "want": "🟡"}.get(cls, "⚪")
                with st.expander(f"{badge} {label} — {item.get('source_name', '')}"):
                    st.write(item.get("raw_text_th", ""))
                    st.caption(f"ID: {item.get('evidence_id', '')} | จำแนก: {cls}")
    except requests.exceptions.ConnectionError:
        st.error(f"เชื่อมต่อ API ไม่ได้ ({API_BASE})")
    except requests.exceptions.HTTPError as e:
        st.error(f"API error: {e.response.status_code}")

st.divider()
st.caption(f"API: {API_BASE}")
