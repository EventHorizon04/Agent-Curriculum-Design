# Handoff: HITL send-back buttons (2026-11-15)

Updated at every task boundary. If you are picking this up, read this file, then the SDD ledger, then `git log --oneline -15`.

## Where things are

- **Branch:** `feat/four-agent-pipeline`. The worktree is shared with running dev servers, so do not switch branches in it. Run `git branch --show-current` before every commit.
- **Spec (approved):** `docs/superpowers/specs/2026-11-15-hitl-send-back-design.md`
- **Plan:** `docs/superpowers/plans/2026-11-15-hitl-send-back.md`, 6 tasks.
- **SDD ledger (source of truth for progress):** `.superpowers/sdd/2026-11-15-hitl-send-back/progress.md`. Task briefs, reports and review packages sit beside it.
- **Process:** superpowers `subagent-driven-development`. Implementers run on sonnet. First reviews run on sonnet with `reviewer-instructions.md` in the workspace. Re-reviews use the `sdd-re-reviewer` agent (opus). The final review runs on opus. Always pass `model`.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Task 1's commit carries a Fable 5.2 trailer, which was correct at the time.

## User decisions this session

- Merge to main is done (0fc21ac). Pushes so far: main, and `feat/four-agent-pipeline` up to b2ff161. **Later commits are not pushed. Ask before pushing.**
- Send-back design:
  - PLO send-back is **per PLO, with a reason**.
  - Need send-back is **the whole set, with a note**.
  - It works in both modes.
- **Option ก:** after a send-back, multi still requires "ตรวจใหม่" before approval. The review loop never rewrites a sent-back PLO; it treats it like a hand-edited one.
  - The user wants to **discuss "the pipeline" after this work**. The topic is not stated yet. Ask them.
- **Temperature stays as is:**
  - `temperature=0` in 6 calls: `llm_clustering` ×2, `need_dedup`, `plo_review_agent`, `single_agent_loop`, `smart_agent`.
  - Every other call uses the provider default.
- **The lock record is made once, after this work (plan Task 6).** Run it on a clean tree with `LLM_CACHE_ENABLED=false`. Create a local tag only, and push only if the user says so.
- **"LLM 3 ตัว"** means the backend model behind the system (e.g. GLM 5.3 flash). The other two models are not named yet. Ask the user before the 3-LLM runs.

## Standing rules

- Never print or commit a secret, `.env`, `.env.demo` or `dist/`. The repo is public.
- Run every alembic command with `-x url=`.
  - **Migration `d9f4a5b6c738` (Task 1) is not applied anywhere.**
  - Applying it to the shared DB `curriculum_agent` needs the user's OK.
  - The backend on :8000 will refuse to start until the DB is migrated, because the schema is behind.
- Don't merge to main without asking.
- Reply in Thai, terse (pordee mode).

## After the 6 tasks (what is left before the comparison experiments)

From Research Plan ระยะ 1 (OneDrive `01 Workspaces/Agentic AI/Research Plan.md`, outside the repo):

1. **Prompt lock:** done in Task 6.
2. **HITL button test:** this feature, then test it on screen in both modes.
3. **3 LLMs:** pick the other two, then smoke-run each in single and multi.
4. **Evaluation framework:**
   - No code exists yet: embedding choice, Hungarian matching, κ, JSD, self-similarity.
   - It needs human inputs: a calibration set and a human–human baseline.
5. **Excel sheet "ระยะ 1":** the template, and an export from the DB.

## Progress log

- Task 1 (PLO send-back columns + migration d9f4a5b6c738): done, 4de25d7, reviewed clean.
- Task 2 (send-back job/route + revalidate keeps the sent-back marker): done, d7f6b15, reviewed clean.
- Task 3 (review loop leaves sent-back PLOs alone): done, 1755aed, reviewed clean.
- Task 4 (single Need run accepts a note): done, 7d0c708, reviewed clean.
- Task 5 (frontend + mock): done, b7b993a, reviewed clean, verified on screen in mock.
- Task 6 (docs + manifest fix + lock-run report): done, ed9d502.
- Final review (opus) → fix wave 53d6750 + 08f3564 (single-mode PLO send-back now on /plo-synthesis; one failing item no longer stops the job; 7 minors). Re-review: 9/9 fixed, 1 Minor parked (single PloSynthesis remounts SendBackList on non-quiet reloads, losing unsent ticks).
- Verified on screen in mock: multi PLO send-back, multi + single Need send-back, single PLO send-back.
- Next: lock record `docs/research/locks/2026-11-15-phase1-lock.md` (clean tree, `LLM_CACHE_ENABLED=false`), local tag, then ask the user about push + migration, then the pipeline discussion.
