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
Copy-Item .env.example .env   # แก้ LLM_PROVIDER/HEAVY_PROVIDER/models ถ้าต้องการ
uv sync --all-extras
```

### 2. Pull LLM models (ครั้งแรกเท่านั้น)

```powershell
ollama pull scb10x/typhoon2-8b-instruct
ollama pull qwen2.5:7b
```

> **Note:** ต้องเปิด Ollama (icon ใน system tray) **เฉพาะเมื่อ** มี provider slot ไหนตั้งเป็น `ollama` — `start-backend.ps1` อ่าน config เองแล้วเช็คให้เท่าที่จำเป็น ถ้าทุก slot ชี้ไป endpoint บนคลาวด์ (ค่า default ตอนนี้) จะข้ามการเช็คนี้ไป

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

## URLs

| Service | URL |
|---|---|
| React UI | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 (minioadmin / minioadmin_dev) |

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
```

## Architecture

5-stage LangGraph pipeline พร้อม HITL checkpoint ทุก stage. Scope จบที่ PLO — YLO/CLO เป็นงานของคณะ:

```
intake → stakeholder_needs → skill_extraction → plo_synthesis → plo_report
```

อ่าน `docs/diagrams/` สำหรับ component diagram และ workflow diagram
