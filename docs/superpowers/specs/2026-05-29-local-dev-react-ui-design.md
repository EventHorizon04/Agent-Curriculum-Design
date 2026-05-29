# Design: Local Dev Deployment + React UI

**Date:** 2026-05-29
**Status:** Approved

## Problem

ตอนนี้ทุก service รันใน Docker รวมถึง `api` และ `ollama` ซึ่งต้องใช้ GPU passthrough ผ่าน Docker ที่มีข้อจำกัดบน Windows และทำให้ dev loop ช้า ต้องการเปลี่ยนให้ backend + LLM รันบน local machine โดยตรงเพื่อใช้การ์ดจอได้เต็มประสิทธิภาพ พร้อมกันนี้เปลี่ยน UI จาก Streamlit เป็น React standalone app

## Architecture

```
Before                              After
────────────────────────────────────────────────────────
Docker  ollama  (GPU passthrough)   Docker  postgres :5432
        postgres                            qdrant   :6333
        qdrant                              minio    :9000/:9001
        minio
        api     (GPU passthrough)   Local   ollama.exe  (GPU direct) :11434
        ui      (streamlit)                 uvicorn     (FastAPI)     :8000
                                            npm run dev (Vite+React)  :5173
```

DB services รันใน Docker เพราะ stateful, portable, ไม่ต้องการ GPU
Backend + LLM รัน local เพราะต้องการ GPU direct access และ hot-reload dev loop
React UI เป็น standalone app แยกจาก backend — start แยกต่างหาก

## Changes

### 1. docker-compose.yml

ลบ services: `ollama`, `api`, `ui`
ลบ volumes: `ollama-data`
เหลือเพียง 3 services:

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16-alpine
    container_name: ca-postgres
    environment:
      POSTGRES_USER: curriculum
      POSTGRES_PASSWORD: curriculum_dev
      POSTGRES_DB: curriculum_agent
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:latest
    container_name: ca-qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant-data:/qdrant/storage
    restart: unless-stopped

  minio:
    image: minio/minio:latest
    container_name: ca-minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin_dev
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio-data:/data
    restart: unless-stopped

volumes:
  postgres-data:
  qdrant-data:
  minio-data:
```

### 2. scripts/start-dev.ps1

ขั้นตอน:
1. Check Python >= 3.11 ผ่าน `uv python list`
2. Check Ollama running ผ่าน `ollama list` (ถ้าไม่ running ให้แสดง error และ exit)
3. `docker compose up -d` เพื่อ start DB services
4. รอ postgres ready ด้วย `pg_isready` loop (timeout 30s)
5. `uv run alembic upgrade head` รัน migrations
6. Start `uvicorn curriculum_agent.api.main:app --reload` ใน background process
7. แสดง URLs: API `:8000`, MinIO console `:9001`, Qdrant `:6333`
8. แสดง hint สำหรับ UI: `cd frontend && npm run dev`

### 3. scripts/stop-dev.ps1

ขั้นตอน:
1. Kill uvicorn background process (by name/PID)
2. `docker compose down`

### 4. frontend/ — Vite + React + TypeScript

โครงสร้าง:
```
frontend/
  src/
    api/                    ← axios client → http://localhost:8000
    pages/
      Intake.tsx            ← Stage 1: program intake
      StakeholderNeeds.tsx  ← Stage 2: stakeholder needs review
      SkillExtraction.tsx   ← Stage 3: skill cluster review
      PloSynthesis.tsx      ← Stage 4: PLO review + approval
      YloDerivation.tsx     ← Stage 5: YLO matrix review + approval
    components/             ← shared UI components
    App.tsx                 ← React Router v6 routes
    main.tsx
  index.html
  vite.config.ts            ← proxy /api/* → localhost:8000
  tsconfig.json
  package.json
```

Dependencies หลัก:
- `react`, `react-dom`, `react-router-dom` v6
- `axios` — HTTP client
- `typescript`
- `vite`

Vite proxy config (หลีกเลี่ยง CORS ใน dev):
```ts
// vite.config.ts
server: {
  proxy: {
    '/api': 'http://localhost:8000'
  }
}
```

### 5. FastAPI CORS

เพิ่ม `CORSMiddleware` ใน `src/curriculum_agent/api/main.py`:
```python
allow_origins=["http://localhost:5173"]
```

### 6. File Cleanup

ลบ:
- `streamlit_app/` — ทั้ง directory
- `Dockerfile.ui` — ใช้สำหรับ Streamlit เท่านั้น

เก็บ:
- `Dockerfile` — reference สำหรับ cloud deploy FastAPI ในอนาคต
- `.env.example` — ไม่ต้องแก้ (ชี้ localhost ทุกอย่างอยู่แล้ว)

### 7. README.md — Getting Started

```markdown
## Prerequisites
- Python 3.11+  (managed via uv)
- Node.js 20+
- Docker Desktop
- Ollama for Windows — https://ollama.com/download/windows

## Quick Start

### 1. Setup
cp .env.example .env

### 2. Pull LLM models (ครั้งแรกเท่านั้น)
ollama pull scb10x/typhoon2-8b-instruct
ollama pull qwen2.5:7b

### 3. Start backend (DB + API)
.\scripts\start-dev.ps1

### 4. Start UI (terminal แยก)
cd frontend
npm install   # ครั้งแรกเท่านั้น
npm run dev

### URLs
- API:          http://localhost:8000
- API docs:     http://localhost:8000/docs
- UI:           http://localhost:5173
- MinIO console: http://localhost:9001
- Qdrant:       http://localhost:6333
```

## What Does NOT Change

- `src/curriculum_agent/` — ทุกไฟล์ใน backend ไม่เปลี่ยน
- `config.py` — defaults ชี้ localhost อยู่แล้ว
- `models.py`, `graph.py` — ไม่แตะ
- `tests/` — ไม่แตะ
- `.env.example` — ไม่แตะ
- `migrations/` — ไม่แตะ

## Constraints

- Ollama ต้องติดตั้งบน Windows native (ไม่ใช่ Docker) — https://ollama.com/download/windows
- Ollama service start อัตโนมัติเมื่อ boot (Windows system tray app) — `start-dev.ps1` ตรวจสอบว่า running อยู่ไหมก่อน start uvicorn
- React UI start แยก — ไม่รวมใน `start-dev.ps1` เพราะเป็น standalone
- Python 3.11+ required — `start-dev.ps1` ตรวจสอบก่อน start
- Node.js 20+ required สำหรับ `frontend/`
