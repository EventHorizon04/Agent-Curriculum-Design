# Auto-run between checkpoints (2026-11-15)

## Intent

Fewer clicks for the designer. Today every stage page has its own run button: the designer adds evidence, opens the Skills page and presses run (multi) or the Needs page and presses run (single), approves Needs by following a "next stage" link, then presses run again on the PLO page. The designer wants the system to run by itself once the input is in, and to stop only where a human decision is needed: at the Need checkpoint and the PLO checkpoint.

## Goals

- One press at the end of evidence input starts everything up to the Needs.
- One press at the Need checkpoint (approve) starts everything up to the PLO checkpoint.
- Both modes (multi and single).

## Non-goals

- No backend change. The jobs and their chaining already exist: `POST /needs/run` runs Agent 1 then Agent 2 (multi) or `single_needs` (single); `POST /plos/run` runs synthesis and chains the review loop (multi) or runs `single_plos` (single).
- No stored record of when Needs were approved (approach ข, deferred; it can be added later without undoing this).
- The LangGraph "รันทั้งชุด" page is untouched and keeps its three checkpoints.
- The run buttons that exist for re-running a stage stay where they are (Skills re-extract, Need send-back, PLO re-run, PLO send-back).

## Anti-goals

- A run that starts without the designer pressing something. Each auto-run starts from an explicit press, so rule 7 (no stage chains into the next without checkpoint approval) still holds: the evidence press *is* the evidence approval, the Need press *is* the Need approval.
- Silently replacing a PLO set the designer already has.
- Any change to prompts, LLM calls, or job parameters. The research lock (`research-lock-phase1-2026-11-15`) is unaffected because the same endpoints run with the same defaults; only who presses changes.

## Approaches

- **ก. Frontend chaining over existing endpoints (chosen by the designer).** Buttons call the existing run routes and navigate to the page that shows progress. No backend, no migration.
- ข. ก plus backend `evidence/submit` and `needs/approve` endpoints that store approval timestamps and start the jobs. Gives a stored approval trail for the research HITL test; about twice the work. Deferred.
- ค. Make the LangGraph session the main path and drop its evidence interrupt. Rejected: the graph is multi-only, has no send-back, and duplicates the stage pages.

## Design

1. **Evidence page (`StakeholderNeeds.tsx`).** The "next stage" link becomes a primary button **"ใส่หลักฐานครบแล้ว เริ่มวิเคราะห์"**, shown only while the program has evidence and no skills or Needs yet (evidence is not locked). Pressing it opens an inline confirm saying evidence is locked once the analysis starts (a copy of the program is the way to change it). Confirm calls `POST /programs/{id}/needs/run` with no note and navigates to `/need-analysis`. A 409/422 shows its Thai `detail` on the page and does not navigate. Once skills or Needs exist the page shows the existing link instead.
2. **Need page (`NeedAnalysis.tsx`), progress.** In multi, the page also follows the `skill_extraction` job (shown with `SKILL_RUN_PLANS.skills`) as well as `need_combination`, and reloads when either ends, so the designer who arrives from the evidence press waits on one page through both agents. Single already follows `single_needs`.
3. **Need page, approval.** The "next stage" link becomes a primary button **"อนุมัติ Need และสร้าง PLO"**, enabled when there are active Needs and no job is running.
   - No PLOs stored: press calls `POST /programs/{id}/plos/run` with no body (backend defaults: validation runs if its slot is enabled, no note) and navigates.
   - PLOs already stored: press opens an inline confirm "ชุด PLO เดิมจะถูกแทนที่ด้วยชุดใหม่"; a plain link "ไปหน้า PLO โดยไม่สร้างใหม่" sits beside it.
   - Navigation target: multi → `/plo-review`; single → `/plo-synthesis` (its checkpoint page).
4. **Review page (`PloReview.tsx`), multi.** Also follows the `plo_synthesis` job (shown with `PLO_SYNTHESIS_PLAN`, or the code-only plan when the run's params say validation is off), so the designer waits on the checkpoint page through synthesis and the chained review loop.
5. **Copy.** The Need page sentences "ระบบไม่รันให้เอง ทุกขั้นต้องผ่านการอนุมัติ" are rewritten to say the system re-runs only when the designer presses; the Pipeline-page empty state is left as is.
6. **Mock mode.** The mock handlers support the two new presses (evidence → `needs/run` → skills + Needs appear; approve → `plos/run` → PLOs + review appear) so the flow can be checked on :5174.
7. **Docs.** CLAUDE.md rule 7 gets a one-line note: the evidence checkpoint is the evidence-page start press and the Need approval press starts the PLO run; `.claude/rules/api-data.md` is not affected (no API change).

## Left to the builder

- Exact component split (a shared confirm-button component or inline state per page).
- How the Need page decides "PLOs stored" (one `GET /plos/` on load is enough).
- Wording of the confirm lines beyond the two given above.
