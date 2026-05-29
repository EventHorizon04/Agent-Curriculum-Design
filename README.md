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
