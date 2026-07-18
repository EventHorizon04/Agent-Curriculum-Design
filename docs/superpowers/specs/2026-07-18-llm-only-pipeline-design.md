# LLM-Only Pipeline Design

**Date:** 2026-07-18
**Branch:** `experiment/llm-only-pipeline`
**Status:** Approved

## Goal

Replace the NLP stack (PyThaiNLP, KeyBERT, BGE-M3 embeddings, KMeans clustering, Qdrant)
with a pure-LLM approach. Motivations (all confirmed by the user):

1. Reduce complexity/dependencies
2. Clustering quality of KMeans is unsatisfactory — LLM groups by contextual meaning
3. Reduce resources (no BGE-M3 in RAM at API startup)
4. Keep `main` as the NLP baseline so both approaches can be compared on the same dataset

## What gets removed

- The entire `src/curriculum_agent/nlp/` package (`embedding.py`, `extraction.py`, `thai_tokenizer.py`)
- `src/curriculum_agent/data/qdrant.py` and all Qdrant writes in `stages/stakeholder_needs.py`
  and `stages/skill_extraction.py`. Qdrant is write-only today (nothing queries it), so no
  feature is lost.
- BGE-M3 warmup block in `api/main.py`
- `qdrant` service in `docker-compose.yml` (postgres + minio + pgadmin remain)
- Dependencies in `pyproject.toml`: `pythainlp`, `sentence-transformers`, `keybert`,
  `scikit-learn`, `qdrant-client`, `torch`, plus the keybert/sklearn mypy override
- The KeyBERT backup-signal step in skill extraction — LLM extraction becomes the only path

## What replaces KMeans: LLM clustering

New flow inside `stages/skill_extraction.py`, prompt in `prompts/cluster_skills.py`:

1. **Dedupe** extracted skills by normalized name (lowercase, trimmed, whitespace-collapsed)
   in pure code. Track which original skill ids map to each unique name.
2. **Single-pass** if unique skills ≤ 150: one heavy-model (Qwen) call receives the numbered
   list of unique skill names and returns clusters as lists of indices.
3. **Map-reduce** if > 150: batches of ~100 → cluster per batch → one merge call that unifies
   cluster labels across batches.
4. **Validation** (Pydantic + pure code): every input index must be assigned exactly once.
   Invalid/hallucinated indices are dropped with a warning; unassigned skills each become a
   singleton cluster — never silently dropped.
5. **Determinism mitigation:** temperature 0 and LLM cache keyed on the sorted unique skill
   list + model name (reuses `LLMCacheRepository`).

## Unchanged

- `SkillCluster` schema, `demand_score` computation (pure code), cluster naming prompt,
  Bloom tagging prompt, HITL flow, all other stages
- `extraction_method` Literal in `models.py` keeps the `"keybert"` value for compatibility
  with existing DB rows

## Testing

- Unit: dedupe normalization, batch splitting, merge mapping, assignment validator
  (missing index → singleton; hallucinated index → dropped)
- Integration: full stage with mocked LLM; update `test_skill_extraction_cache.py` and
  `test_end_to_end.py` which currently reference embed/KMeans

## Comparison plan

`main` keeps the NLP pipeline. This branch is LLM-only. Run the same seed dataset through
both and compare cluster quality by hand before deciding whether to merge.
