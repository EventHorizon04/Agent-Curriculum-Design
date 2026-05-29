# Local Dev Deployment + React UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ย้าย FastAPI + Ollama ออกจาก Docker ให้รัน local เพื่อใช้ GPU โดยตรง และเปลี่ยน UI จาก Streamlit เป็น Vite + React + TypeScript standalone app

**Architecture:** Docker รัน 3 DB services เท่านั้น (postgres, qdrant, minio) ส่วน backend รัน local ผ่าน PowerShell script. React frontend เป็น standalone SPA ที่ start แยกต่างหาก ทำงานผ่าน CORS กับ FastAPI ที่ localhost:8000

**Tech Stack:** Docker Compose (DB only), PowerShell 5.1+, FastAPI + uvicorn (local), Vite + React 18 + TypeScript + axios + React Router v6, Ollama Windows native

---

## File Map

| Action | Path | Purpose |
|---|---|---|
| Modify | `docker-compose.yml` | เหลือแค่ postgres/qdrant/minio |
| Modify | `src/curriculum_agent/api/main.py` | เพิ่ม CORSMiddleware |
| Modify | `.gitignore` | เพิ่ม .uvicorn.pid และ frontend/node_modules |
| Create | `scripts/start-dev.ps1` | start DB + migrations + uvicorn |
| Create | `scripts/stop-dev.ps1` | stop uvicorn + docker compose down |
| Create | `frontend/package.json` | Vite + React + TypeScript + deps |
| Create | `frontend/vite.config.ts` | dev server + proxy config |
| Create | `frontend/tsconfig.json` | TypeScript config |
| Create | `frontend/index.html` | HTML entrypoint |
| Create | `frontend/src/main.tsx` | React entrypoint |
| Create | `frontend/src/api/client.ts` | axios instance → localhost:8000 |
| Create | `frontend/src/components/StageLayout.tsx` | shared nav + layout wrapper |
| Create | `frontend/src/App.tsx` | BrowserRouter + 5 routes |
| Create | `frontend/src/pages/Intake.tsx` | Stage 1 |
| Create | `frontend/src/pages/StakeholderNeeds.tsx` | Stage 2 |
| Create | `frontend/src/pages/SkillExtraction.tsx` | Stage 3 |
| Create | `frontend/src/pages/PloSynthesis.tsx` | Stage 4 |
| Create | `frontend/src/pages/YloDerivation.tsx` | Stage 5 |
| Delete | `streamlit_app/` | ทั้ง directory |
| Delete | `Dockerfile.ui` | ไม่ใช้แล้ว |
| Create | `README.md` | Getting Started ใหม่ |

---

## Task 1: Trim docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: เขียนทับ docker-compose.yml**

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

- [ ] **Step 2: Validate config**

Run: `docker compose config`
Expected: YAML output แสดง 3 services (postgres, qdrant, minio) ไม่มี error

- [ ] **Step 3: Commit**

```
git add docker-compose.yml
git commit -m "chore: remove ollama/api/ui from docker-compose, DB services only"
```

---

## Task 2: Add CORS to FastAPI

**Files:**
- Modify: `src/curriculum_agent/api/main.py`

- [ ] **Step 1: Verify tests pass ก่อนแก้**

Run: `uv run pytest --tb=no -q`
Expected: `40 passed`

- [ ] **Step 2: แก้ main.py เพิ่ม CORSMiddleware**

เขียนทับ `src/curriculum_agent/api/main.py`:

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from curriculum_agent.api.routes import clusters, evidence, plos, programs, ylos

app = FastAPI(title="Curriculum Design Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(programs.router, prefix="/programs", tags=["programs"])
app.include_router(evidence.router, prefix="/programs/{program_id}/evidence", tags=["evidence"])
app.include_router(clusters.router, prefix="/programs/{program_id}/clusters", tags=["clusters"])
app.include_router(plos.router, prefix="/programs/{program_id}/plos", tags=["plos"])
app.include_router(ylos.router, prefix="/programs/{program_id}/ylos", tags=["ylos"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 3: Verify tests ยังผ่าน**

Run: `uv run pytest --tb=no -q`
Expected: `40 passed`

- [ ] **Step 4: Commit**

```
git add src/curriculum_agent/api/main.py
git commit -m "feat: add CORS middleware allowing localhost:5173"
```

---

## Task 3: Create PowerShell dev scripts

**Files:**
- Create: `scripts/start-dev.ps1`
- Create: `scripts/stop-dev.ps1`
- Modify: `.gitignore`

- [ ] **Step 1: สร้าง scripts/ directory**

```powershell
New-Item -ItemType Directory -Force scripts
```

- [ ] **Step 2: สร้าง scripts/start-dev.ps1**

```powershell
#Requires -Version 5.1
<#
.SYNOPSIS
  Start local dev environment: DB services (Docker) + FastAPI (local)
.DESCRIPTION
  Checks prerequisites, starts postgres/qdrant/minio via Docker Compose,
  runs Alembic migrations, then starts uvicorn in the background.
  React UI must be started separately: cd frontend && npm run dev
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "   OK: $msg" -ForegroundColor Green }
function Write-Fail { param([string]$msg) Write-Host "   FAIL: $msg" -ForegroundColor Red; exit 1 }

# --- 1. Check Python >= 3.11 ---
Write-Step "Checking Python version..."
try {
    $pyVer = & uv run python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
    $parts = $pyVer -split '\.'
    if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
        Write-Fail "Python 3.11+ required. Got $pyVer"
    }
    Write-Ok "Python $pyVer"
} catch {
    Write-Fail "uv not found. Install uv: https://docs.astral.sh/uv/"
}

# --- 2. Check Ollama is running ---
Write-Step "Checking Ollama..."
try {
    $null = & ollama list 2>&1
    if ($LASTEXITCODE -ne 0) { throw "exit $LASTEXITCODE" }
    Write-Ok "Ollama running"
} catch {
    Write-Fail "Ollama not running. Start Ollama from the system tray first. https://ollama.com/download/windows"
}

# --- 3. Start Docker DB services ---
Write-Step "Starting DB services (postgres, qdrant, minio)..."
docker compose up -d
if ($LASTEXITCODE -ne 0) { Write-Fail "docker compose up failed" }
Write-Ok "Containers started"

# --- 4. Wait for postgres ready ---
Write-Step "Waiting for postgres..."
$timeout = 30
$elapsed = 0
while ($elapsed -lt $timeout) {
    $result = docker exec ca-postgres pg_isready -U curriculum 2>&1
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
    $elapsed++
}
if ($elapsed -ge $timeout) { Write-Fail "Postgres not ready after ${timeout}s" }
Write-Ok "Postgres ready"

# --- 5. Run migrations ---
Write-Step "Running Alembic migrations..."
uv run alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Fail "Migration failed" }
Write-Ok "Migrations applied"

# --- 6. Start uvicorn in background ---
Write-Step "Starting FastAPI (uvicorn)..."
$proc = Start-Process -FilePath "uv" `
    -ArgumentList "run", "uvicorn", "curriculum_agent.api.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000" `
    -PassThru -NoNewWindow
$proc.Id | Out-File -FilePath ".uvicorn.pid" -Encoding utf8
Write-Ok "uvicorn started (PID $($proc.Id))"

# --- Done ---
Write-Host ""
Write-Host "=== Dev environment ready ===" -ForegroundColor Yellow
Write-Host "  API:           http://localhost:8000"
Write-Host "  API docs:      http://localhost:8000/docs"
Write-Host "  MinIO console: http://localhost:9001"
Write-Host "  Qdrant:        http://localhost:6333"
Write-Host ""
Write-Host "  UI (start separately):" -ForegroundColor Yellow
Write-Host "    cd frontend && npm run dev   ->  http://localhost:5173"
Write-Host ""
Write-Host "  Stop: .\scripts\stop-dev.ps1"
```

- [ ] **Step 3: สร้าง scripts/stop-dev.ps1**

```powershell
#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }

# --- 1. Kill uvicorn ---
Write-Step "Stopping uvicorn..."
if (Test-Path ".uvicorn.pid") {
    $savedPid = [int](Get-Content ".uvicorn.pid" -Raw).Trim()
    try {
        Stop-Process -Id $savedPid -Force -ErrorAction Stop
        Write-Host "   Stopped PID $savedPid" -ForegroundColor Green
    } catch {
        Write-Host "   PID $savedPid not found (already stopped)" -ForegroundColor Yellow
    }
    Remove-Item ".uvicorn.pid" -Force
} else {
    Write-Host "   No .uvicorn.pid found — stopping by name"
    Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue | Stop-Process -Force
}

# --- 2. Docker compose down ---
Write-Step "Stopping Docker services..."
docker compose down
Write-Host "   Done." -ForegroundColor Green
```

- [ ] **Step 4: เพิ่ม entries ใน .gitignore**

เพิ่มบรรทัดเหล่านี้ใน `.gitignore` (ถ้าไม่มีไฟล์ให้สร้างใหม่):

```
.uvicorn.pid
frontend/node_modules/
frontend/dist/
```

- [ ] **Step 5: ตรวจ syntax PowerShell**

```powershell
powershell -NonInteractive -Command "& { . '.\scripts\start-dev.ps1' -WhatIf }" 2>&1
```

ถ้า error เรื่อง `-WhatIf` ไม่รองรับ นั่นปกติ — ดูแค่ว่าไม่มี parse error ก่อน `-WhatIf` line

หรือตรวจด้วย:
```powershell
Get-Command .\scripts\start-dev.ps1
```
Expected: แสดง CommandType: ExternalScript ไม่มี parse error

- [ ] **Step 6: Commit**

```
git add scripts/start-dev.ps1 scripts/stop-dev.ps1 .gitignore
git commit -m "feat: add PowerShell dev scripts for local backend"
```

---

## Task 4: Scaffold Vite + React + TypeScript frontend

**Files:**
- Create: `frontend/` (scaffold via npm)

- [ ] **Step 1: Scaffold Vite project**

Run จาก root ของ project:

```powershell
npm create vite@latest frontend -- --template react-ts
```

Expected: สร้าง `frontend/` directory พร้อม `src/`, `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`

- [ ] **Step 2: Install dependencies**

```powershell
cd frontend
npm install
npm install axios react-router-dom
npm install -D @types/react-router-dom
cd ..
```

- [ ] **Step 3: เขียนทับ vite.config.ts**

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/programs': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
```

- [ ] **Step 4: ลบ boilerplate ที่ไม่ใช้**

```powershell
Remove-Item -Force frontend/src/App.css -ErrorAction SilentlyContinue
Remove-Item -Force frontend/src/assets/react.svg -ErrorAction SilentlyContinue
```

- [ ] **Step 5: Commit**

```
git add frontend/
git commit -m "feat: scaffold Vite + React + TypeScript frontend"
```

---

## Task 5: สร้าง API client และ StageLayout

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/components/StageLayout.tsx`

- [ ] **Step 1: สร้าง frontend/src/api/client.ts**

```ts
import axios from 'axios'

const api = axios.create({
  baseURL: 'http://localhost:8000',
  headers: { 'Content-Type': 'application/json' },
})

export default api
```

- [ ] **Step 2: สร้าง frontend/src/components/StageLayout.tsx**

```tsx
import { NavLink, Outlet } from 'react-router-dom'

const stages = [
  { path: '/', label: 'Stage 1: Intake' },
  { path: '/stakeholder-needs', label: 'Stage 2: Stakeholder Needs' },
  { path: '/skill-extraction', label: 'Stage 3: Skill Extraction' },
  { path: '/plo-synthesis', label: 'Stage 4: PLO Synthesis' },
  { path: '/ylo-derivation', label: 'Stage 5: YLO Derivation' },
]

export default function StageLayout() {
  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: 'sans-serif' }}>
      <nav style={{ width: 240, padding: 16, borderRight: '1px solid #ddd', background: '#f9f9f9' }}>
        <h2 style={{ fontSize: 14, marginBottom: 16 }}>Curriculum Agent</h2>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {stages.map((s) => (
            <li key={s.path} style={{ marginBottom: 8 }}>
              <NavLink
                to={s.path}
                end={s.path === '/'}
                style={({ isActive }) => ({
                  fontWeight: isActive ? 'bold' : 'normal',
                  color: isActive ? '#0066cc' : '#333',
                  textDecoration: 'none',
                  fontSize: 13,
                })}
              >
                {s.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main style={{ flex: 1, padding: 24 }}>
        <Outlet />
      </main>
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```
git add frontend/src/api/ frontend/src/components/
git commit -m "feat: add axios client and StageLayout component"
```

---

## Task 6: สร้าง 5 stage pages + App routing

**Files:**
- Create: `frontend/src/pages/Intake.tsx`
- Create: `frontend/src/pages/StakeholderNeeds.tsx`
- Create: `frontend/src/pages/SkillExtraction.tsx`
- Create: `frontend/src/pages/PloSynthesis.tsx`
- Create: `frontend/src/pages/YloDerivation.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: สร้าง frontend/src/pages/Intake.tsx**

```tsx
import { useState } from 'react'
import api from '../api/client'

export default function Intake() {
  const [status, setStatus] = useState<string>('')

  async function checkHealth() {
    try {
      const res = await api.get<{ status: string }>('/health')
      setStatus(`API: ${res.data.status}`)
    } catch {
      setStatus('API not reachable — is uvicorn running?')
    }
  }

  return (
    <div>
      <h1>Stage 1: Program Intake</h1>
      <p>อัปโหลดเอกสารหลักสูตรและกรอกข้อมูลพื้นฐานของโปรแกรม</p>
      <button onClick={checkHealth}>Test API connection</button>
      {status && <p style={{ marginTop: 8, color: status.includes('not') ? 'red' : 'green' }}>{status}</p>}
    </div>
  )
}
```

- [ ] **Step 2: สร้าง frontend/src/pages/StakeholderNeeds.tsx**

```tsx
export default function StakeholderNeeds() {
  return (
    <div>
      <h1>Stage 2: Stakeholder Needs</h1>
      <p>ตรวจสอบและอนุมัติข้อมูลความต้องการจากผู้มีส่วนได้ส่วนเสีย</p>
    </div>
  )
}
```

- [ ] **Step 3: สร้าง frontend/src/pages/SkillExtraction.tsx**

```tsx
export default function SkillExtraction() {
  return (
    <div>
      <h1>Stage 3: Skill Extraction</h1>
      <p>ตรวจสอบ skill clusters ที่ extract ได้จาก job market data</p>
    </div>
  )
}
```

- [ ] **Step 4: สร้าง frontend/src/pages/PloSynthesis.tsx**

```tsx
export default function PloSynthesis() {
  return (
    <div>
      <h1>Stage 4: PLO Synthesis</h1>
      <p>ตรวจสอบและอนุมัติ Program Learning Outcomes (PLO) ที่สังเคราะห์ได้</p>
    </div>
  )
}
```

- [ ] **Step 5: สร้าง frontend/src/pages/YloDerivation.tsx**

```tsx
export default function YloDerivation() {
  return (
    <div>
      <h1>Stage 5: YLO Derivation</h1>
      <p>ตรวจสอบ Yearly Learning Outcomes (YLO) matrix และ Bloom level coverage</p>
    </div>
  )
}
```

- [ ] **Step 6: เขียนทับ frontend/src/App.tsx**

```tsx
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import StageLayout from './components/StageLayout'
import Intake from './pages/Intake'
import StakeholderNeeds from './pages/StakeholderNeeds'
import SkillExtraction from './pages/SkillExtraction'
import PloSynthesis from './pages/PloSynthesis'
import YloDerivation from './pages/YloDerivation'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<StageLayout />}>
          <Route index element={<Intake />} />
          <Route path="stakeholder-needs" element={<StakeholderNeeds />} />
          <Route path="skill-extraction" element={<SkillExtraction />} />
          <Route path="plo-synthesis" element={<PloSynthesis />} />
          <Route path="ylo-derivation" element={<YloDerivation />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
```

- [ ] **Step 7: เขียนทับ frontend/src/main.tsx**

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

- [ ] **Step 8: ตรวจ TypeScript compile**

```powershell
cd frontend
npx tsc --noEmit
cd ..
```
Expected: ไม่มี error

- [ ] **Step 9: Smoke test ใน browser**

```powershell
cd frontend
npm run dev
```

เปิด http://localhost:5173 ตรวจว่า:
- Nav แสดง 5 stages
- คลิก nav ระหว่าง stages ได้ (routing ทำงาน)
- Stage 1: กด "Test API connection" → ถ้า uvicorn running แสดง `API: ok`

กด Ctrl+C เพื่อ stop dev server

- [ ] **Step 10: Commit**

```
git add frontend/src/
git commit -m "feat: add 5 stage pages and React Router routing"
```

---

## Task 7: File cleanup

**Files:**
- Delete: `streamlit_app/`
- Delete: `Dockerfile.ui`

- [ ] **Step 1: ลบ streamlit_app/**

```powershell
Remove-Item -Recurse -Force streamlit_app/
```

- [ ] **Step 2: ลบ Dockerfile.ui**

```powershell
Remove-Item -Force Dockerfile.ui
```

- [ ] **Step 3: ตรวจ backend tests ยังผ่าน**

Run: `uv run pytest --tb=no -q`
Expected: `40 passed`

- [ ] **Step 4: Commit**

```
git add -A
git commit -m "chore: remove Streamlit app and Dockerfile.ui"
```

---

## Task 8: สร้าง README.md

**Files:**
- Create: `README.md`

- [ ] **Step 1: สร้าง README.md**

```markdown
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
cp .env.example .env        # แก้ LIGHT_MODEL/HEAVY_MODEL ถ้าต้องการ
uv sync --all-extras
```

### 2. Pull LLM models (ครั้งแรกเท่านั้น)

```powershell
ollama pull scb10x/typhoon2-8b-instruct
ollama pull qwen2.5:7b
```

### 3. Start backend (DB + migrations + API)

```powershell
.\scripts\start-dev.ps1
```

### 4. Start UI (terminal แยก)

```powershell
cd frontend
npm install       # ครั้งแรกเท่านั้น
npm run dev
```

## URLs

| Service | URL |
|---|---|
| React UI | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 (minioadmin / minioadmin_dev) |
| Qdrant dashboard | http://localhost:6333/dashboard |

## Stop

```powershell
.\scripts\stop-dev.ps1
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

5-stage LangGraph pipeline พร้อม HITL checkpoint ทุก stage:

```
intake → stakeholder_needs → skill_extraction → plo_synthesis → ylo_derivation
```

อ่าน `docs/diagrams/` สำหรับ component diagram และ workflow diagram
```

- [ ] **Step 2: Commit**

```
git add README.md
git commit -m "docs: add README with local dev quick start"
```

---

## Self-Review Checklist

- [x] docker-compose.yml → Task 1
- [x] CORS FastAPI → Task 2
- [x] start-dev.ps1 (Python check + Ollama check + DB + migration + uvicorn) → Task 3
- [x] stop-dev.ps1 → Task 3
- [x] .gitignore entries → Task 3
- [x] Vite scaffold + proxy config → Task 4
- [x] axios client → Task 5
- [x] StageLayout + nav → Task 5
- [x] 5 stage pages → Task 6
- [x] App.tsx routing → Task 6
- [x] main.tsx → Task 6
- [x] Delete streamlit_app/ → Task 7
- [x] Delete Dockerfile.ui → Task 7
- [x] README.md → Task 8
- [x] ทุก task มี commit ของตัวเอง
- [x] tests ยังผ่านหลัง Task 2 และ Task 7
