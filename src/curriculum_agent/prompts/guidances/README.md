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

All four have been reviewed line by line against the running prompts:
`.scratch/prompt-guidances/market-need-synthesis-review.md` and
`.scratch/prompt-guidances/three-file-review.md`.

## What has been adopted (2026-09-26)

The text half of all four is in the builders now — the `--check` output of
`scripts/dump_prompts.py` is the way to read what a prompt actually says today,
never this directory.

| adopted | left | why it was left |
|---|---|---|
| `market_need_synthesis` rules 1, 7, 8 and `rationale_th` | the `ผู้ปฏิบัติงาน` subject | a decision this repo already made the other way — see `.scratch/prompt-guidances/issues/01` |
| `skill_extraction`: the definition of a skill, the "not a skill" list, occupational identity, the job identity test | Bloom "lowest necessary level" · rule 10's confidence rubric · `{program_context}` in the system message | Bloom runs through `merge_bloom`'s max and would lower a whole Need; nothing reads `confidence`; the context line would pull per-program text into a fingerprint kept identical across programs. The job identity test was removed for a day on one eval run and put back when the control run reproduced both symptoms without it — see `.scratch/prompt-guidances/three-file-review.md` |
| `skill_clustering` rules 4 and 6, plus the curriculum-level line | rules 5, 8, 9 | all three govern `label_th`, which `cluster_skill_names` discards the moment it arrives — whether asking for it improves the partition at all is an open experiment |
| `cluster_merging` rules 2, 3, 4, 5, 6, 8 | rule 9 (`merge_rationale_th`) | a new response field moves `_CLUSTERING_CONTRACT` directly, and it is a reason for a grouping whose label nothing reads |

The "land them in one commit" advice above was followed for the text, and the
measured cost was the one the review predicted: 24 live cache rows retired, 14
evidence items re-extracted. What is left all touches a response schema, so it
still has a fingerprint move to pay when it lands.
