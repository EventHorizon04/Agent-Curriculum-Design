# SMART validation as a tool-using agent — design

**Date:** 2026-09-09
**Supersedes:** the soft-judge design in `specs/2026-08-03-intake-trim-and-smart-rubric-design.md` (its rubric survives intact; only the mechanism changes) and the retry-loop mechanism in `plans/2026-07-09-plo-agentic-design.md` (a historical record — not edited).

## The problem

The SMART gate was two pieces that did not talk to each other.

**The soft judge could not see enough to judge.** One `complete_light` call per PLO, given the statement, the degree level, the duration and the Need statements. So `achievable_ok` had to infer the Bloom level from the sentence — the prompt never sent `bloom_level` — and `relevant_needs_ok` judged against Need summaries without ever seeing the evidence behind them.

**The repair was blind.** `_build_fix_prompt` sent the old statement plus a fixed Thai hint per criterion, three times, with no new information between rounds. A statement that needed a different verb and a statement that needed a narrower object got the same paragraph.

**The reason was thrown away.** The surviving `fails` list was logged and dropped. A designer saw "ไม่ผ่าน SMART หลัง retry 3 ครั้ง" and could not tell which of three checks did it, let alone why.

**Two rules existed only as prompt text.** "Exactly one recognized Bloom verb" and "two verbs only if adjacent" had no code behind them, because the Thai verb vocabulary did not exist in the repository — `obe-principles.md` carries the table in English.

And one bug made all of it worse: the M hard check tested `word in statement`, which in unsegmented Thai flags `รักษา` (holds รัก), `จำแนก`/`จำลอง` (จำ) and `ความรู้`/`เรียนรู้` (รู้). A PLO using **จำแนก** — itself a sound Understand-level verb — hard-failed Measurable, spent all three repairs arguing with a hint about a word it never used, and escalated.

## Shape

One agent on a new `VALIDATION_*` slot, per PLO, run concurrently.

```
draft (synthesis slot)
   ↓
validation agent (validation slot, multi-turn)
   ├─ check_hard          → the pure-code verdict, read not reimplemented
   ├─ get_need            → this PLO's Needs, from context
   ├─ get_evidence        → 600-char excerpt, cited only, 3 per PLO
   ├─ list_sibling_plos   → the rest of the set
   ├─ bloom_lookup        → the Thai verb table
   └─ request_repair      → an instruction; complete_synthesis writes the Thai
   ↓
hard_failures(final statement)      ← authoritative, every exit path
   ↓
escalated = bool(fails)
```

### A structured action loop, not native tool-calling

Instructor is wired `Mode.JSON` for every slot in `llm._get_client`. Reading a `tool_calls` envelope would mean dropping to the raw client and hand-parsing JSON — forbidden here — or keying the cached client on `(provider, mode)`, changing the one function all five slots share for the benefit of one. It would also tie the loop to providers that implement tool-calling, when every provider field accepts `None` to mean "follow `LLM_PROVIDER`" and running the whole pipeline on one endpoint is a supported arrangement.

So the model returns one `ValidationStep` per turn — `reasoning_th` first, because field order is schema order is generation order — carrying a discriminated `CallTool | RequestRepair | Finish`. The loop executes it and appends the result as the next user turn. A malformed action is a Pydantic `ValidationError`, which Instructor re-asks with the error attached.

`llm.py` needed no multi-turn machinery: `_complete` already passes the message list through, so an assistant turn in it works unchanged. The loop owns the list.

### Immutable rule 5, held by construction

Three mechanisms, none of them conventions the model could talk past:

1. `Finish` carries five soft booleans and a diagnosis. It has **no field that can clear a hard failure**, and `check_hard` is a read of the pure function whose result is never retained as the verdict.
2. `validate_and_build` runs `hard_failures` on the final statement on **every** exit path, and that call alone sets `smart_escalated`. The agent's only causal route to the outcome is getting `complete_synthesis` to write a better sentence, which code then re-judges — so its influence is monotone: it can shrink the failure list, never declare it empty.
3. `RequestRepair` has **no `statement_th`**. The Thai a designer submits to MHESI still comes from the Thai-first synthesis slot; a helpful model handed that field would put "a repair is never answered by a different model than wrote the draft" one field away from false.

A test drives an agent that signs off on a statement containing เข้าใจ and pins that it is escalated anyway.

### What the agent may see

Each tool's refusals are the design, not error handling:

- `get_need` reads the Needs the stage already loaded, never a repository — so it cannot reach a Need outside this PLO's trail, let alone another program's.
- `get_evidence` serves 600-character excerpts of **cited** evidence only, three per PLO, with `truncated`/`total_chars` so the agent knows it read a slice. The loop is the one new place a prompt can accumulate the corpus one turn at a time, invisibly to the designer, so the cap belongs in the tool rather than in a prompt asking nicely — and without the truncation flags the agent reasons about a forty-page สภาวิชาชีพ standard as if the first paragraph were all of it, the defect `chunk_evidence_text` exists to prevent.
- `ValidationContext` has **no `note_th` field**. The designer's note reaches the draft prompt and nothing else; a validator that could read it could relay the wording into an instruction, and the note would arrive at a repair prompt second-hand.
- A repeated identical tool call is refused without spending a provider call. A repeat is not progress.

### Two phases, and why

`list_sibling_plos` needs the set, and the stage used to draft-and-judge one PLO at a time. So `run()` splits: phase A drafts every selected Need, phase B validates every draft against the whole drafted set.

The siblings are the **drafts**, not the repaired statements. Validating against post-repair siblings is a second full pass at N× cost with no fixed point, and sibling context is advisory input to a diagnosis rather than a verdict of its own.

Overlap can only ever be a **soft** finding, recorded under `S_object`. Redundancy is a property of the set and PLOs are validated concurrently: ten validators asked pairwise can each answer "not a duplicate" while the set holds two near twins, or PLO3 and PLO7 can flag each other, both escalate, both get repaired independently, and converge again. Set-level enforcement belongs in `plo_report`, not in ten independent judgements trying to agree.

Slot selection stays pure code ahead of any call, and `gather` preserves input order, so `PLO1` is still the most-demanded Need. Switching to `as_completed` for a progress bar would make `PLO4` mean a different outcome between runs, and designers cite these ids.

### Budgets

8 turns, 3 repairs (the gate's existing policy, inherited rather than restated), 3 evidence reads, 2 consecutive malformed steps, 240s per PLO, 3 concurrent loops.

The concurrency bound is separate from `llm_max_concurrency` on purpose: it bounds *loops*, and a loop is serial, so N loops is N in-flight calls. Sharing the knob would let a deployment that raises the per-call ceiling for extraction multiply the validation bill.

Every exit produces a verdict. A provider error or an exhausted budget yields a **code-only** result: every soft verdict true, no manufactured findings, `smart_validated_by="code_only"`. An agent that could not run must not escalate anything — the same discipline the light judge had, now covering the whole gate.

### What a verdict records

- `SMARTCheck.findings` — one `SmartFinding` (criterion, severity, Thai note) per problem, hard and soft in one list. Rides inside the existing `smart_check` JSONB column, so the richest field needed no migration.
- `smart_validated_by` — `agent` / `code_only` / `stale` / `legacy`. Four different facts the UI must not conflate; `legacy` is the honest answer for a pre-agent row.
- `smart_diagnosis_th` — the overall reason, in Thai, that a designer acts on.

The transcript is **not** persisted. It is the largest object in the row, `PLO` is the response model of five endpoints, and `plo_report` re-upserts every PLO on every checkpoint run. If it must be stored it belongs in an audit table keyed `(program_id, plo_id, run_at)`.

`soft_flags` stays `list[str]`. Narrowing it to the enum makes a row carrying a retired code unreadable — `R_alignment` shipped for months — so one stale string would take out a program's whole PLO list on GET rather than one field.

## Rollout

Replace outright; no feature flag. This project has no behaviour toggle in `config.py`, the agent and the old gate write different shapes, and the staged commits already give a revertible path. The kill switch already exists and is better: `VALIDATION_PROVIDER=` skips the agent and uses the code-only fallback, which had to be written anyway for an endpoint outage.

It took a live run to find that the switch, as first shipped, did not exist. `""` was not a member of the field's `Literal`, so `VALIDATION_PROVIDER=` in a `.env` file stopped the API booting; leaving it unset resolved to `LLM_PROVIDER` and ran the agent regardless; and the loop's guard read `not validation_provider and not llm_provider`, whose second half can never be true because `llm_provider` is a `Literal` with no empty member — `ValidationReason.DISABLED` was unreachable and untested. The lesson is not about this switch: a configuration state that nothing exercises is a claim, not a feature, and the three places it had to hold (the field, the resolution, the guard) each looked right on its own.

## Where I would push back

- **`bloom_lookup` as a tool is the cheapest turn to delete.** The table is static data in this repository, so a tool call to read a constant costs a round trip and gives the model a chance not to make it. The verbs for the draft's declared level could go in the system prompt, leaving the tool for verbs the agent suspects. Not done: it would spend prompt budget on every PLO to save a turn on some.
- **The Thai verb table wants a specialist's review** before it gains any authority. It is advisory precisely because a sound verb it forgot would otherwise hard-fail Specific and escalate.
- **The diagnosis is written by a model that will not write the fix.** The repair instruction therefore has to stand on its own, which the prompt states and the tests pin — but nothing can *prove* an instruction is self-contained. Watch for repairs that fix something the agent did not ask about.
