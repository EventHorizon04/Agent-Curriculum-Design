from __future__ import annotations

import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.title("ขั้นตอนที่ 0 — ข้อมูลหลักสูตร (Intake)")

if "program_id" in st.session_state:
    st.success(f"หลักสูตรปัจจุบัน: **{st.session_state['program_id']}**")

with st.form("intake_form"):
    col1, col2 = st.columns(2)
    with col1:
        program_id = st.text_input("รหัสหลักสูตร *", placeholder="cs-2025")
        name_th = st.text_input("ชื่อหลักสูตร (ภาษาไทย) *")
        name_en = st.text_input("ชื่อหลักสูตร (ภาษาอังกฤษ) *")
        field = st.text_input("สาขาวิชา *", placeholder="Computer Science")
    with col2:
        degree_level = st.selectbox("ระดับปริญญา", ["bachelor", "master", "doctoral"])
        duration_years = st.number_input("จำนวนปีการศึกษา", min_value=1, max_value=8, value=4)
        faculty = st.text_input("คณะ *")
        university = st.text_input("มหาวิทยาลัย *")

    vision_th = st.text_area("วิสัยทัศน์หลักสูตร (ภาษาไทย) *")
    objectives_raw = st.text_area(
        "วัตถุประสงค์หลักสูตร (ภาษาไทย) — แต่ละรายการ 1 บรรทัด *"
    )
    submitted = st.form_submit_button("บันทึกและเริ่มประมวลผล Stage 0")

if submitted:
    required = [program_id, name_th, name_en, field, faculty, university, vision_th, objectives_raw]
    if not all(required):
        st.error("กรุณากรอกข้อมูลที่มีเครื่องหมาย * ให้ครบถ้วน")
    else:
        objectives = [line.strip() for line in objectives_raw.splitlines() if line.strip()]
        payload = {
            "program_id": program_id,
            "name_th": name_th,
            "name_en": name_en,
            "field": field,
            "degree_level": degree_level,
            "duration_years": int(duration_years),
            "faculty": faculty,
            "university": university,
            "vision_th": vision_th,
            "program_objectives_th": objectives,
        }
        with st.spinner("กำลังบันทึกและเริ่ม pipeline..."):
            try:
                resp = requests.post(f"{API_BASE}/programs/", json=payload, timeout=30)
                resp.raise_for_status()
                st.session_state["program_id"] = program_id
                st.success(f"บันทึกหลักสูตร **{program_id}** สำเร็จ — ไปที่หน้า 2 เพื่ออัปโหลดหลักฐาน")
            except requests.exceptions.ConnectionError:
                st.error(f"เชื่อมต่อ API ไม่ได้ ({API_BASE}) — ตรวจสอบว่า backend รันอยู่")
            except requests.exceptions.HTTPError as e:
                st.error(f"API error: {e.response.status_code} — {e.response.text}")

st.divider()
st.caption(f"API: {API_BASE}")
