# Development Phases Reference

Three phases from PoC to production. Each phase has clear exit criteria — don't move to the next until they're met.

---

## Phase 1 — MVP, single field, manual data input (4–6 weeks)

**Goal:** prove the 5-stage pipeline works end-to-end on one program with hand-curated data. Get an honest answer to: does the agent produce PLO/YLO that a curriculum designer would actually use?

**Scope choices:**
- One field only (recommend Computer Science or Data Science — easy to verify)
- One degree level (bachelor's, 4 years)
- 100–200 hand-curated job postings + 1 subject benchmark (มคอ.1) + 1 professional council standard
- Single-user UI in Streamlit
- LLM via Ollama (Typhoon 8B + Qwen 14B/32B), no paid API yet

**Week-by-week:**

### Week 1 — foundations
- [ ] Set up repo structure (`src/curriculum_agent/...`)
- [ ] Docker Compose with Ollama, Postgres, Qdrant, FastAPI, Streamlit
- [ ] Pull Typhoon 2 8B and Qwen 2.5 14B locally
- [ ] Implement Pydantic schemas from `references/data-schemas.md`
- [ ] Test basic LLM call via Instructor → Pydantic round trip
- [ ] Set up Postgres tables for `ProgramMetadata`, `StakeholderEvidence`

### Week 2 — Stage 0 + Stage 1
- [ ] Streamlit form for `ProgramMetadata` intake
- [ ] File upload UI for stakeholder documents (PDF, Word, plain text)
- [ ] Apache Tika or unstructured.io for document text extraction
- [ ] Stage 1: store as `StakeholderEvidence`, run classification prompt (need / requirement / want)
- [ ] BGE-M3 embedding of evidence into Qdrant
- [ ] Save first stage checkpoint

### Week 3 — Stage 2 (the data-science stage)
- [ ] PyThaiNLP tokenization pipeline
- [ ] Stage 2 part A: skill extraction prompt per evidence item → `ExtractedSkill`
- [ ] Stage 2 part B: KeyBERT for keyword backup, validate against LLM extraction
- [ ] Stage 2 part C: BERTopic to cluster skills, then LLM names each cluster
- [ ] Compute `demand_score` (frequency × recency × stakeholder breadth)
- [ ] Streamlit page showing skill clusters with evidence drill-down
- [ ] Designer review checkpoint: drop / merge / rename clusters

### Week 4 — Stage 3 (PLO synthesis)
- [ ] Stage 3 prompt with full SMART/Bloom rules from `references/prompts.md`
- [ ] Generate 4–6 PLOs from approved clusters, with `source_cluster_ids` populated
- [ ] SMART validator pass (light model, separate prompt)
- [ ] Streamlit page showing PLOs with evidence trail (click PLO → see clusters → see evidence)
- [ ] Designer can edit, regenerate single PLO, or accept

### Week 5 — Stage 4 (YLO derivation)
- [ ] Stage 4 prompt per PLO → 4 YLOs with progressive Bloom
- [ ] `YLOMatrix.validate_coverage()` runs and surfaces issues
- [ ] Streamlit grid view: PLO × Year showing YLO
- [ ] Designer can edit individual YLO, view rationale

### Week 6 — polish + qualitative eval
- [ ] LangGraph wiring all 5 stages with interrupt at each boundary
- [ ] Versioning of PLO/YLO (every save creates new version)
- [ ] Run end-to-end with two more sample programs
- [ ] Show output to 2–3 real curriculum designers, get feedback
- [ ] Iterate on prompts based on feedback

**Phase 1 exit criteria:**
- Pipeline runs end-to-end without manual intervention between stages (besides review)
- Output is judged "useful starting point" by at least 2 curriculum designers
- All artifacts trace back to source evidence (drill-down works)
- Streamlit UI is usable without developer help

If exit criteria not met, iterate on prompts and UX before moving to Phase 2.

---

## Phase 2 — Automated data acquisition (4–6 weeks)

**Goal:** remove the bottleneck of hand-curating evidence. The agent should find its own data given a program field.

### Week 7–8 — scrapers
- [ ] Playwright scraper for one major Thai job site (start with JobThai or JobsDB)
- [ ] Rate limiting, robots.txt respect, retry logic
- [ ] Field-to-keyword mapping: "Computer Science" → search terms
- [ ] Job posting parser → `StakeholderEvidence` with metadata (title, salary, posted_date, company)
- [ ] Add second job site
- [ ] Schedule: refresh on demand or weekly cron

### Week 9 — document parsing automation
- [ ] PDF parser for มคอ.1 documents (Thai academic format)
- [ ] Detect and parse standard sections (objectives, expected outcomes, curriculum structure)
- [ ] LLM-assisted parser as fallback when format varies
- [ ] Professional council standard parser for major councils (วิศวกร, แพทย์, สถาปนิก, etc.)

### Week 10 — alumni & survey integration
- [ ] CSV import for alumni surveys (common format)
- [ ] LLM extraction of skills from open-ended survey responses
- [ ] Structured matching with cluster names from existing programs

### Week 11 — evidence trail
- [ ] Implement full citation chain in UI: YLO → PLO → cluster → skill → evidence → source
- [ ] Export evidence pack (PDF) for accreditation review
- [ ] Search/filter on evidence by stakeholder type, date, keyword

### Week 12 — Qdrant migration & retrieval
- [ ] Move from local SQLite vectors to Qdrant cluster
- [ ] Hybrid search (keyword + semantic) for evidence retrieval
- [ ] Re-rank with cross-encoder for precision

**Phase 2 exit criteria:**
- New program field can be set up by uploading metadata only — agent finds 200+ pieces of evidence on its own
- Document parsing works on 5+ real มคอ.1 documents from different fields
- Evidence trail UI is complete

---

## Phase 3 — Production hardening (4 weeks)

**Goal:** the system is ready for multiple curriculum designers across faculties.

### Week 13 — export formats
- [ ] CHECO format export (with proper field mapping)
- [ ] มคอ.2 template export
- [ ] Curriculum mapping matrix as Excel
- [ ] Word document with full PLO/YLO + rationale + evidence summary

### Week 14 — multi-tenant
- [ ] Faculty / department scoping in DB
- [ ] User roles: designer / reviewer / admin
- [ ] Audit log of all PLO/YLO edits

### Week 15 — serving
- [ ] Replace Ollama with vLLM for production
- [ ] Add load balancing and auto-restart
- [ ] Background job queue (Celery/Arq) for long-running stages

### Week 16 — evaluation framework
- [ ] Compare agent output to existing real curricula (with permission)
- [ ] Designer rating UI: rate generated PLO 1–5 with comments
- [ ] Track metrics: time to draft PLO, edit distance from generated to final, designer satisfaction
- [ ] Use metrics to drive next iteration of prompts

**Phase 3 exit criteria:**
- 3+ faculties using the system in real curriculum revision
- Average time to first usable PLO draft < 1 day (vs typical 2–4 weeks manual)
- Designer satisfaction ≥ 4/5 on output quality
- All outputs traceable for accreditation

---

## Anti-patterns to avoid

**Don't skip Phase 1 to "save time."** The pipeline has many failure modes that only surface end-to-end. Skip the MVP and you'll spend Phase 2 unwinding bad architectural decisions.

**Don't add a feature unless it's on this plan.** Scope creep in PoC kills timelines. Park new ideas in a backlog and reassess at phase boundaries.

**Don't optimize the LLM prompt before the pipeline works.** Get end-to-end output first, even if PLO quality is mediocre. Then iterate.

**Don't fork into multi-program support before Phase 3.** Single program in Phase 1 and 2 keeps state simple.

**Don't write your own RAG framework.** Use existing libraries (LangChain retrieval, LlamaIndex if needed). Custom RAG is a side quest that costs weeks.

**Don't ignore Thai-specific issues.** Test on Thai text from day 1. Tokenization, embedding quality, and LLM Thai fluency all need explicit verification, not assumed.

---

## When the user wants to start

Default starting point: **Phase 1 Week 1**. Have them confirm:
1. Which field for the MVP? (recommend their own field for fastest judgment)
2. Hardware available? (determines model choice — Typhoon 8B for any modern laptop, Qwen 32B needs RTX 3090+ or M3 Max)
3. Budget for paid LLM fallback? (yes → can swap in Claude/GPT for Stage 3–4; no → all-OS path)

Then scaffold the repo, write `docker-compose.yml`, and run the first end-to-end smoke test by end of Week 1.
