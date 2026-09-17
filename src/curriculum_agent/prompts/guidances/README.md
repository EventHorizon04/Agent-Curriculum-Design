# Prompt guidance drafts

These four documents are **drafts of how each LLM-facing prompt should read**, not
the prompts themselves. Nothing imports them: every prompt this pipeline sends is
a Python literal returned by a builder in `prompts/`, and no code in `src/`,
`tests/` or `scripts/` opens this directory. Editing a file here changes nothing
that runs.

| draft | the prompt it is about | builder |
|---|---|---|
| `market_need_synthesis.md` | one skill group → one Need sentence | `prompts/summarize_need.py` |
| `skill_extraction.md` | evidence window → skills | `prompts/extract_skills.py` |
| `skill_clustering.md` | skill names → groups | `prompts/cluster_skills.py` |
| `cluster_merging.md` | groups → fewer groups | `prompts/cluster_skills.py` |

## Before adopting anything from one of these

Three of the four sit behind a **cache fingerprint**. `_extraction_contract_fingerprint`
hashes the whole extract_skills system prompt plus its response schema, and
`_clustering_contract_fingerprint` hashes all three clustering prompt variants —
so changing one character of those prompts turns every `llm_cache` row written
before the change into a `stale-contract` row that can never be hit again, and the
whole corpus is re-extracted at full cost. Only `market_need_synthesis.md`'s
prompt is outside any cache key. Review the other three together and land them in
one commit, so the re-extraction is paid once.

A draft is also not a drop-in replacement for the prompt it describes. Each one
ends with a `ประเด็น / Prompt เดิม / Prompt ปรับปรุง / เหตุผล` rationale table that
is a record for the reader rather than an instruction to the model, and none of
them leaves a slot for `program_context` or for the designer note
(`NOTE_POLICY_TH` / `append_note`) that the live builders already wire in.

The first of these has been reviewed line by line against the running prompt:
`.scratch/prompt-guidances/market-need-synthesis-review.md`.
