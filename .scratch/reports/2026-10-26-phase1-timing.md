# Phase 1 timing and migration check — 2026-10-27

Branch `feat/four-agent-pipeline` @ 07b41de. Run on a **copy** of the dev DB
(`curriculum_phase1`, cloned from `curriculum_agent` with `createdb -T`); the
original DB was not touched and is still at revision `d1e2f3a4b5c6`.

## Migrations

On the copy: `upgrade head` → `downgrade -2` → `upgrade head`, all clean.
- After upgrade: 35/35 Needs got a one-element `ksec_categories` (24 S, 5 K, 6 EC); `skill_groups` empty (expected — groups exist only after Agent 1 runs).
- After downgrade: `ksec_category` restored on 35/35 rows.

## POST /programs/program/needs/run (largest corpus: 14 evidence items, ~868k chars)

| Agent | Job | Wall time | Notes |
|---|---|---|---|
| 1 | skill_extraction (extract + group) | 0.8 s | every extraction window and clustering call was an LLM-cache hit — not a cold-run figure |
| 2 | need_combination (sentences + dedup + merge) | 116 s | 13 groups, concurrent sentence calls (typhoon-v2.5-30b-a3b-instruct) |

Both jobs succeeded; Agent 2 was started by Agent 1's `on_success` 57 ms after Agent 1 finished.
Agent 1 clustered S 53+14, EC 17, K 6+1 unique names into 13 groups (budget EC=2, K=1, S=7).

## Dedup / merge

`need_merge: groups proposed=2 accepted=2 unfolded_for_floor=1 sentence_failed=0 merged=1 multi_tag_merged=0 core_needs=9->9`

- One 3-Need group was unfolded by the merge floor (folding it would leave < 4 core Needs among the in-scope written Needs).
- One merged Need (2 originals, tag S): "ต้องการบัณฑิตที่ใช้เทคโนโลยีดิจิทัลเป็นเครื่องมือสนับสนุนกระบวนการแปลภาษาไทยและภาษาจีน".
- Stored: 14 Needs, 12 active, 1 merged, 0 multi-tag.

## Finding: 5 of 13 Need sentences failed — output truncated at 512 tokens

5 groups (4 S, 1 EC) ended as `[เรียกโมเดลไม่สำเร็จ]` fallbacks. Every failed attempt has
`finish_reason='length'` with `completion_tokens=512` (the provider's default output cap;
the call sets no `max_tokens`). The model writes `not_covered_indices` with one entry for
**every** listed member (`"reason_code": "low_freq"`, empty `note_th`), so large groups run out
of budget before the JSON closes. Instructor's retries resend the same request and hit the
same cap.

This is not introduced by phase 1: the summarize prompt is byte-identical to main (golden
test), and the model and provider are the same. The stored main-DB Needs for this program
(0 fallbacks) were most likely produced before `not_covered_indices` was added.
Concurrency is not the cause (the failure is per-response length, not rate limiting).

Fix options (not applied): set an explicit `max_tokens` on the Need-sentence call
(e.g. 1536), and/or tell the prompt to list `not_covered_indices` only for members the
sentence deliberately excludes, not every unlisted one.

## Fix verified (aa13f26)

`STATEMENT_MAX_TOKENS = 2048` passed as `max_tokens` on both Need-sentence calls
(per-group and merged). Re-ran Agent 2 alone (`POST /needs/combine/run`) on the same copy:

- 0 `finish_reason='length'`, 0 statement failures, 0 fallback Needs (was 5/13).
- Agent 2 wall time 58 s (was 116 s — the failed groups no longer burn three attempts each).
- `need_merge: groups proposed=3 accepted=1 unfolded_for_floor=0 sentence_failed=0 merged=1 multi_tag_merged=0 core_needs=9->8`
- Stored: 14 Needs, 12 active.

## Cold run — LLM cache cleared on the copy (aa13f26 backend)

`delete from llm_cache` on `curriculum_phase1` only (52 extraction + 18 clustering rows), then `POST /needs/run`.

| Step | Wall time | Budget |
|---|---|---|
| Agent 1 — extraction (14 evidence items, 86 skills, 1 dropped ungrounded) | **281 s** | 300 s |
| Agent 1 — grouping (6 clustering calls → 10 groups) | 35 s | 300 s |
| Agent 2 — 10 sentences + dedup + 1 merged sentence | **290 s** | 300 s |

Both long steps finished, but each used **>93% of its 300 s budget** on this corpus. A
somewhat larger corpus will time out at extraction or at Agent 2 — that is phase 5
(batching / budgets), and the per-step budget is the first thing to revisit.

Agent 2 detail: 0 `finish_reason='length'` (fix holds). 2 groups (C, S) were *rejected by the
sentence validator* after 3 attempts and shipped as `[ต้องทบทวน]` for the designer — the
pre-existing "write it yourself" path, not a provider failure. Their retries are a large share
of the 290 s. `need_merge: groups proposed=2 accepted=2 unfolded_for_floor=0 sentence_failed=1
merged=1 multi_tag_merged=0 core_needs=9->8 dedup_call=ok`. Stored: 11 Needs, 9 active.
