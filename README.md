# Curriculum Design Agent

AI agent ช่วย curriculum designers ออกแบบหลักสูตรอุดมศึกษาตามมาตรฐาน MHESI และ OBE (Outcome-Based Education)

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ | via [uv](https://docs.astral.sh/uv/) |
| Node.js | 20+ | https://nodejs.org/ |
| Docker Desktop | latest | https://www.docker.com/products/docker-desktop/ |
| Ollama | latest | https://ollama.com/download/windows |

## Quick Start

### 1. First-time setup

```powershell
Copy-Item .env.example .env   # แก้ LLM_PROVIDER/CLUSTERING_PROVIDER/models ถ้าต้องการ
uv sync --all-extras
```

### 2. LLM provider

บน branch `feat/four-agent-pipeline` ทุก LLM slot ใช้ OpenRouter โมเดล `z-ai/glm-5.3-flash` เป็นค่า default (`PIPELINE_PROVIDER` / `PIPELINE_MODEL`) — ใส่ `OPENROUTER_API_KEY` ใน `.env` อย่างเดียวก็รันได้ ต้องการแยก provider ราย slot ดูคำอธิบายใน `.env.example`

> **Note:** ต้องเปิด Ollama **เฉพาะเมื่อ** มี slot ไหนตั้ง provider เป็น `ollama` — `start-backend.ps1` อ่าน config แล้วเช็คให้เอง ถ้าทุก slot ชี้ไป endpoint บนคลาวด์ (ค่า default) จะข้ามการเช็คนี้

### 3. Start data services (postgres + minio + migrations)

```powershell
.\scripts\start-services.ps1
```

### 4. Start backend (terminal เดิมได้)

```powershell
.\scripts\start-backend.ps1
```

ไม่ start container เอง — ถ้า DB ยังไม่ขึ้นหรือ schema ตามหลัง migration จะหยุดพร้อมบอกว่าต้องรันอะไร
แก้โค้ด backend แล้ว restart แค่ตัวนี้ ไม่ต้องรอ Docker

### 5. Start UI (terminal แยก)

```powershell
.\scripts\start-frontend.ps1      # npm install ให้เองถ้ายังไม่มี node_modules
```

รันค้างในเทอร์มินัล — Ctrl+C คือวิธีปิด

> ทางลัด: `.\scripts\start-dev.ps1` = services + backend ในคำสั่งเดียว (UI ยังต้องแยก)

### UI แบบไม่ต้องมี backend (mock mode)

```powershell
cd frontend
npm run dev:mock                  # http://localhost:5174 — ข้อมูลจำลองใน browser ไม่เรียก API
```

ใช้ดูหน้าตา UI หรือทดสอบ flow ได้โดยไม่ต้องเปิด DB / backend / LLM

## URLs

| Service | URL |
|---|---|
| React UI | http://localhost:5173 (หน้าแรก = วิธีใช้, หลักสูตรของฉัน = `/my-programs`) |
| React UI (mock) | http://localhost:5174 |
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 (login ด้วย `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` ใน `.env` — ค่าเริ่มต้นดู `.env.example`) |

## Stop

```powershell
.\scripts\stop-backend.ps1                # API อย่างเดียว
.\scripts\stop-services.ps1               # containers (ข้อมูลใน named volume อยู่ครบ)

.\scripts\stop-dev.ps1                    # ทั้งคู่ ตามลำดับที่ถูกต้อง
.\scripts\stop-dev.ps1 -KeepServices      # ปิด API ทิ้ง DB ไว้ — กรณีที่ใช้บ่อยสุดตอนพัฒนา
```

## Development

```powershell
# Run tests
uv run pytest

# Lint & format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run mypy src/

# Frontend (ใน frontend/)
npm run build
npm run lint
```

## Architecture

LangGraph pipeline ที่อาจารย์ผู้ออกแบบหลักสูตรอนุมัติเป็นช่วง ๆ (human-in-the-loop). Scope จบที่ PLO — YLO/CLO เป็นงานของคณะ:

```
intake → stakeholder_needs → skill_extraction → need_analysis → plo_synthesis → plo_review → plo_report
          [อนุมัติหลักฐาน]                         [อนุมัติ Need]                     [อนุมัติชุด PLO]
```

หลักสูตรเลือกโหมดตอนสร้าง และเปลี่ยนภายหลังไม่ได้:

| โหมด | ทำงานอย่างไร |
|---|---|
| **Multi-agent** (default) | Agent 1 สกัดและจัดกลุ่มทักษะ → Agent 2 รวมเป็น Need → Agent 3 สังเคราะห์ PLO พร้อม SMART vote → Agent 4 review loop ทบทวนและส่งกลับแก้อัตโนมัติ |
| **Single-agent** | agent ตัวเดียวอ่านหลักฐานเองแล้วเขียน Need (ระบบไม่รับ finish ถ้า Need หลักไม่ถึง 6 ข้อ) และ PLO ไม่มี vote และไม่มี review loop |

ทั้งสองโหมด PLO ทุกข้อต้องย้อนกลับไปหาหลักฐานได้ และผ่าน SMART hard check ที่เป็น pure code

รายละเอียดการตัดสินใจและกฎ OBE อยู่ใน `CLAUDE.md` และ skill `.claude/skills/curriculum-design-agent/` · diagram ใน `docs/diagrams/`
