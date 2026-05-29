# Recommended Project Structure

When scaffolding the curriculum design agent codebase, follow this layout. Pydantic models, prompts, and schemas live in well-known places so future contributors can find them.

```
curriculum-design-agent/
├── docker-compose.yml              # PoC services stack
├── Dockerfile                      # FastAPI backend
├── Dockerfile.ui                   # Streamlit frontend
├── pyproject.toml                  # Python project config (uv or poetry)
├── .env.example                    # config template
├── README.md
├── src/
│   └── curriculum_agent/
│       ├── __init__.py
│       ├── config.py               # pydantic-settings, reads .env
│       ├── models.py               # Pydantic schemas (from scripts/pydantic_schemas.py)
│       ├── llm.py                  # Ollama/Instructor client setup, dual-model routing
│       ├── graph.py                # LangGraph state machine (from scripts/langgraph_agent.py)
│       ├── prompts/
│       │   ├── __init__.py
│       │   ├── stage_1_classify.py
│       │   ├── stage_2_extract.py
│       │   ├── stage_2_cluster_name.py
│       │   ├── stage_3_plo.py
│       │   ├── stage_4_ylo.py
│       │   └── smart_validator.py
│       ├── stages/
│       │   ├── __init__.py
│       │   ├── intake.py
│       │   ├── stakeholder_needs.py
│       │   ├── skill_extraction.py
│       │   ├── plo_synthesis.py
│       │   └── ylo_derivation.py
│       ├── data/
│       │   ├── __init__.py
│       │   ├── postgres.py         # SQLAlchemy/SQLModel setup
│       │   ├── qdrant.py           # vector store client
│       │   ├── minio_store.py      # raw file storage
│       │   └── repositories.py     # CRUD per model
│       ├── nlp/
│       │   ├── __init__.py
│       │   ├── thai_tokenizer.py   # PyThaiNLP wrapper
│       │   ├── embedding.py        # BGE-M3 client
│       │   └── extraction.py       # KeyBERT, BERTopic
│       ├── scrapers/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── jobthai.py
│       │   └── jobsdb.py
│       ├── parsers/
│       │   ├── __init__.py
│       │   ├── tika_parser.py
│       │   └── mko1_parser.py      # มคอ.1 specific
│       ├── exporters/
│       │   ├── __init__.py
│       │   ├── checo.py
│       │   ├── mko2.py             # มคอ.2 export
│       │   └── excel_matrix.py
│       └── api/
│           ├── __init__.py
│           ├── main.py             # FastAPI app
│           ├── routes/
│           │   ├── programs.py
│           │   ├── evidence.py
│           │   ├── clusters.py
│           │   ├── plos.py
│           │   └── ylos.py
│           └── deps.py
├── streamlit_app/
│   ├── app.py                      # main entry point
│   └── pages/
│       ├── 1_intake.py
│       ├── 2_evidence.py
│       ├── 3_clusters.py
│       ├── 4_plos.py
│       └── 5_ylos.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # pytest fixtures
│   ├── unit/
│   │   ├── test_models.py          # Pydantic validators (forbidden words, etc.)
│   │   ├── test_ylo_matrix.py      # coverage and Bloom monotonicity
│   │   └── test_smart_check.py
│   └── integration/
│       ├── test_stage_3_plo.py     # mocked LLM, real prompt
│       └── test_end_to_end.py
└── scripts/
    ├── seed_models.sh              # ollama pull commands
    ├── init_db.sql                 # Postgres schema
    └── eval_against_real_curriculum.py  # Phase 3 evaluation
```

## Key conventions

**Stage isolation:** each `stages/<stage>.py` is the only place that orchestrates that stage. It calls into `prompts/`, `data/`, `nlp/`, etc., but other stages don't import from it.

**Prompts are first-class:** prompt strings live in their own files, returned by functions that take typed input. This makes prompts diff-able and reviewable.

```python
# prompts/stage_3_plo.py
from curriculum_agent.models import ProgramMetadata, SkillCluster

def build_plo_synthesis_prompt(
    metadata: ProgramMetadata,
    clusters: list[SkillCluster]
) -> str:
    cluster_summary = "\n".join(
        f"- [{c.cluster_id}] {c.canonical_name_th}: {c.description_th} "
        f"(demand={c.demand_score:.2f}, evidence={len(c.source_evidence_ids)})"
        for c in clusters
    )
    return f"""คุณเป็นผู้เชี่ยวชาญด้านการออกแบบหลักสูตรระดับอุดมศึกษา...

บริบทหลักสูตร:
- สาขาวิชา: {metadata.field}
- ระดับ: {metadata.degree_level} ({metadata.duration_years} ปี)
- วิสัยทัศน์: {metadata.vision_th}

ข้อมูล skill clusters:
{cluster_summary}

(rules per references/prompts.md)
"""
```

**Repository pattern for data:** all DB access goes through `data/repositories.py` so swapping Postgres for another DB later doesn't ripple through the codebase.

**Test the validators first:** Pydantic validators on PLO and YLO are critical guardrails. Test them with both passing and failing examples before testing any LLM-driven code.

**Use `uv` for dependency management** (or `poetry` if you prefer). Faster than pip and the lockfile keeps team in sync.

```toml
# pyproject.toml essentials
[project]
name = "curriculum-agent"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "instructor>=1.0",
    "openai>=1.20",            # used as Ollama client (OpenAI-compatible)
    "langgraph>=0.0.40",
    "sqlalchemy>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "qdrant-client>=1.8",
    "minio>=7.2",
    "pythainlp>=5.0",
    "sentence-transformers>=2.5",
    "keybert>=0.8",
    "bertopic>=0.16",
    "scikit-learn>=1.4",
    "pandas>=2.2",
    "polars>=0.20",
    "duckdb>=0.10",
    "playwright>=1.42",
    "beautifulsoup4>=4.12",
    "httpx>=0.27",
    "unstructured>=0.13",
    "loguru>=0.7",
    "streamlit>=1.32",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.3",
    "mypy>=1.9",
]
```
