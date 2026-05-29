# Tech Stack Reference

Open-source first. Paid alternatives are listed where they provide a meaningful upgrade (typically Stage 3–4 synthesis quality). Read this when choosing a tool, justifying a decision, or onboarding a new component.

## LLM layer

### Recommended primary models

**Typhoon 2 8B** (SCB 10X, Llama-based, fine-tuned for Thai)
- License: Llama 3 community license
- Use for: light tasks across all stages — classify document, extract entities, summarize chunk, normalize skill names
- Hardware: runs on RTX 3060 12GB, RTX 4060 Ti 16GB, Apple Silicon 16GB+
- Why: best Thai instruction-following among small open-source models

**Qwen 2.5 14B / 32B** (Alibaba)
- License: Apache 2.0 (very permissive)
- Use for: medium-to-heavy reasoning, structured output with Instructor
- Hardware: 14B on 16GB GPU, 32B needs 24GB+ or quantization
- Why: excellent multilingual including Thai, strong tool/function calling

**Llama 3.3 70B** (Meta)
- License: Llama 3 community license
- Use for: Stage 3–4 PLO/YLO synthesis where reasoning quality matters most
- Hardware: needs Q4 quantization to fit in 24GB; full precision needs A100
- Use via Groq or Together AI for cheap hosted inference if local is too heavy

### Dual-model pattern (use this)

```python
# Light model for high-volume / low-stakes tasks
LIGHT_MODEL = "typhoon2:8b"  # or "qwen2.5:7b"

# Heavy model for synthesis / reasoning
HEAVY_MODEL = "qwen2.5:32b"  # or "llama3.3:70b" or paid API
```

Stages 0–2 mostly use LIGHT_MODEL. Stages 3–4 use HEAVY_MODEL. Wire through config so a user can swap without code changes.

### Inference engines

| Engine | Use when | Strengths | Weaknesses |
|--------|----------|-----------|------------|
| **Ollama** | PoC, local dev | Trivial setup, model swap, OpenAI-compatible API | Throughput limited |
| **vLLM** | Production | High throughput, batching, paged attention | Setup complexity |
| **llama.cpp** | CPU / edge | Runs anywhere, no GPU needed | Slow for big models |
| **TGI** (HF Text Generation Inference) | HF-centric stacks | Good production features | Less common than vLLM |

For PoC: Ollama. For production: vLLM behind FastAPI gateway.

### Embedding models

**BGE-M3** (BAAI) — first choice
- Multilingual, Thai works well, supports dense + sparse + multi-vector retrieval
- Run via sentence-transformers or BGE's own client

**multilingual-e5-large** — alternative
- Solid Thai support, smaller memory footprint
- Use if BGE-M3 is too heavy for the deployment target

**WangchanX** embedding models — Thai-specific alternative
- Specialized for Thai, may help with domain-specific Thai academic vocabulary
- Worth A/B testing against BGE-M3 on a real corpus

### Paid alternatives (only if budget allows)

- **Anthropic Claude (Sonnet/Opus)** — best instruction-following for Stage 3–4 synthesis. Worth paying for the PLO/YLO writing step specifically.
- **OpenAI GPT-4o / o1** — comparable quality, similar pricing
- **Groq** (Llama 3.3 70B / Mixtral) — extremely fast hosted inference of OS models, cheap
- **Together AI / Fireworks** — hosted OS models, pay-per-token

Recommended hybrid: open-source for Stages 0–2 (high token volume), paid API for Stages 3–4 if quality matters and budget exists.

## Agent orchestration

### LangGraph (recommended)
- Stateful workflow with explicit nodes
- Built-in `interrupt` for human-in-the-loop checkpoints (critical for this use case)
- Persistent state via SQLite/Postgres checkpoint
- Integrates with LangChain ecosystem

### Alternatives
- **smolagents** (Hugging Face) — lightweight, less features, less ceremony
- **CrewAI** — multi-agent role-play model, overkill here
- **AutoGen** (Microsoft) — chat-based multi-agent, also overkill
- **Plain Python state machine** — viable for very simple flows, but you lose tooling

Stick with LangGraph unless you have a specific reason not to.

### Structured output

- **Instructor** + **Pydantic** — patches OpenAI client, returns Pydantic objects from LLMs
- **Outlines** — alternative, more complex setup
- **LangChain's structured output** — works but Instructor is cleaner

Always use one of these. Never parse JSON from LLM strings by hand for production data.

## Thai NLP

**PyThaiNLP** is the standard. It handles:
- Tokenization (which Thai needs because there are no word boundaries)
- POS tagging
- NER
- Soundex
- Thai-aware text normalization

Other useful libraries:
- **WangchanBERTa** — pretrained Thai BERT for classification fine-tuning
- **attacut** — alternative tokenizer, sometimes more accurate than PyThaiNLP default
- **deepcut** — older but well-known Thai tokenizer

For this project, PyThaiNLP for tokenization + sentence-transformers (BGE-M3) for embeddings covers ~90% of Thai NLP needs.

## Skill extraction & text mining

- **KeyBERT** — keyword extraction using BERT embeddings, language-agnostic when paired with multilingual encoder
- **BERTopic** — modern topic modeling, much better than LDA for short texts
- **scikit-learn** — TF-IDF, clustering (K-Means, HDBSCAN), classical ML
- **Polars** or **Pandas** — dataframe ops; Polars is faster for large corpora
- **DuckDB** — SQL on Parquet/CSV without a DB server, excellent for ad-hoc EDA on job postings

## Vector store

| Option | When to use |
|--------|-------------|
| **Qdrant** | First choice. Hybrid search built in, good Python client, easy Docker deploy |
| **ChromaDB** | Even simpler than Qdrant, fewer features. Fine for PoC |
| **pgvector** | If Postgres is already in the stack — reduces service count |
| **Weaviate** | Alternative to Qdrant, similar feature set |
| **Milvus** | Enterprise scale, overkill for this use case |

For PoC: ChromaDB or Qdrant. For production: Qdrant or pgvector.

## Data acquisition

- **Playwright** — JS-rendered sites (LinkedIn, JobsDB). Async support is nice.
- **BeautifulSoup + httpx** — static HTML, fast and simple
- **Scrapy** — large-scale scraping with built-in queue/retry. Overkill for PoC.
- **Apache Tika** — extracts text from many formats (PDF, Word, PowerPoint). Java-based, run as a service.
- **unstructured.io** — modern alternative, Python-native, handles layout/tables better than naive PDF readers
- **pypdf** / **pdfplumber** — for simple PDFs only
- **docx2txt** / **python-docx** — for Word documents

For Thai job site scraping: respect robots.txt and rate-limit. Some sites have terms of service that prohibit scraping; check before deploying.

## Backend / API

- **FastAPI** — async-friendly, automatic OpenAPI docs, Pydantic native
- **Pydantic v2** — data validation, settings management (`pydantic-settings`)
- **Uvicorn** / **Gunicorn** — ASGI servers
- **Celery** or **Arq** — background jobs (if scraping/heavy processing should be async)

## Frontend

- **Streamlit** — fastest path to UI for PoC. Single-file Python apps.
- **Gradio** — alternative, more ML-demo focused
- **Next.js + Shadcn** — when production polish is needed; significantly more code

For PoC, Streamlit. Don't optimize prematurely.

## Storage

- **PostgreSQL** — structured data: programs, PLOs, YLOs, version history
- **SQLite** — fine for single-user PoC; swap to Postgres before multi-user
- **DuckDB** — analytical queries on Parquet files; doesn't replace transactional DB
- **MinIO** — S3-compatible object storage for raw files (job postings, PDFs)

## Deployment

### PoC: Docker Compose
Services to include:
1. Ollama (LLM serving)
2. Qdrant (vector DB)
3. Postgres (structured data)
4. MinIO (object storage)
5. FastAPI backend
6. Streamlit frontend

A reference `docker-compose.yml` is in `scripts/`.

### Production: Kubernetes
Only when scale demands it. Add:
- Ingress + TLS
- Horizontal autoscaling on FastAPI
- Persistent volumes for Postgres/Qdrant/MinIO
- Replace Ollama with vLLM behind a service

## Hardware sizing

| Component | Min spec | Recommended |
|-----------|----------|-------------|
| LLM (Typhoon 8B) | 12GB VRAM | RTX 3060 12GB or M2/M3 16GB |
| LLM (Qwen 32B Q4) | 24GB VRAM | RTX 3090 / 4090 or M3 Max 36GB |
| LLM (Llama 70B Q4) | 40GB VRAM | A100 40GB or M3 Ultra |
| Embedding (BGE-M3) | 4GB VRAM, runs on CPU | Any modern CPU |
| Vector DB (Qdrant, 1M vectors) | 8GB RAM | 16GB |
| Postgres + app stack | 4GB RAM | 16GB |

For small teams: one workstation with RTX 4090 or M3 Max can host the entire PoC.

For team-wide PoC: hosted LLM inference via Groq/Together AI removes the GPU requirement entirely; you only need a small server for the app stack.

## When in doubt

- Default to Python 3.11+
- Default to Ollama for local LLM
- Default to LangGraph for orchestration
- Default to Pydantic for everything that crosses a boundary
- Default to Streamlit for any UI in PoC stage
- Default to Docker Compose for deployment
- Default to PostgreSQL when you outgrow SQLite

Don't introduce a new tool unless an existing one is genuinely insufficient.
