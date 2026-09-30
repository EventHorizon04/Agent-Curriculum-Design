# Fold duplicate Needs before PLO synthesis — design

**Date:** 2026-09-30
**Amends:** immutable rule 6 in `CLAUDE.md` ("each drafted from one Need").

## The problem

`plo_synthesis` gives every in-scope Need its own PLO slot. Nothing compares the
Needs against each other, so two Needs asking for the same capability become two
PLOs. On the stored run (program `program`, 13 Needs, 9 PLOs) that happens four
times:

| Needs | What both ask for |
|---|---|
| PLO2 `252f…`, PLO3 `6a45…` (and arguably PLO7 `d7c4…`) | translation with AI-assisted quality control |
| PLO4 `afe6…`, PLO5 `befb…` | ethics, adapting to change, leadership |
| OPT1 `5dd3…`, unused `1b4f…` | designing a digital language tool |

The "one PLO per Need" invariant (`cited_need_ids`, `plos_citing`) is unaffected:
it stops one Need being cited twice, and says nothing about two Needs that mean
the same thing. Today the designer can fold them by hand through
`POST /plos/from-needs`. This design does the first pass automatically, before
any PLO is drafted.

## Why not a code-only similarity

Evidence overlap looked like the free signal and does not separate anything. The
corpus has few evidence items, so every Need draws on the same documents:

| Pair | Evidence Jaccard | Duplicate? |
|---|---|---|
| PLO1 marketing ~ PLO4 ethics | 0.55 | no |
| PLO1 marketing ~ PLO2 translation | 0.55 | no |
| PLO2 ~ PLO3 | 0.45 | yes |
| PLO4 ~ PLO5 | below 0.20 | yes |

The true PLO4/PLO5 pair shares less evidence than either false pair. No threshold separates the true pairs from the shared-source pairs. Lexical
comparison of Thai needs segmentation the repo does not have, and this branch
dropped embeddings on purpose (`specs/2026-07-18-llm-only-pipeline-design.md`).
What is left is a model reading the sentences, once, as a set.

## Shape

```
plo_synthesis.run
   ├─ scope filter (unchanged)
   ├─ need_dedup.find_duplicate_groups   ← new: one call, need_dedup slot
   │     └─ accept_groups                ← pure code, drops what breaks a rule
   ├─ build units: accepted groups + singletons
   ├─ slot selection over units          ← ceiling, ordering, ids: as today
   └─ draft + validate each slot         ← unchanged; a slot already takes a list
```

Nothing downstream of slot selection changes. `_Slot.needs` is already a list,
`build_plo_from_need_prompt` already has a plural branch (the merge route uses
it), `validate_and_build` already unions every Need's evidence into the PLO's
trail and sets `is_optional=all(...)`. Both ways of running the stage — the graph
and `POST /plos/run` — go through `plo_synthesis.run`, so one insertion covers
both. The manual merge route does not call the dedupe step: a designer choosing
Needs by hand has already made the decision.

## The call

**Slot:** a new `need_dedup` slot, declared once in `config.SLOTS` between
`need_combination` and `plo_synthesis`. Default provider `openrouter`, model left
on the provider default (llama-3.3-70b, the clustering model): the task returns a
grouping, not Thai prose, which is the line the slot table already draws. Its own
knob rather than a shared one for the reason `CLAUDE.md` gives about `heavy` —
a shared slot cannot be moved without moving its neighbour. It is `disableable`
like validation: `NEED_DEDUP_PROVIDER=""` skips the call and gives today's
behaviour, which is both the outage fallback and the A/B baseline for measuring
this change. `complete_need_dedup` in `llm.py`; `describe_target()` and the
warm-up list pick it up from `SLOTS` with no further edits.

**Input** (`prompts/need_dedup.py`, `build_need_dedup_prompt`): the program
context line (`build_program_context_th`), then one line per in-scope Need —
a short label (`N1`, `N2`, … in demand order), its KSEC tag, and `statement_th`.
Labels, not `need_id`s: a UUID is 36 characters the model has to copy exactly,
and `supporting_indices` already showed indices are what a model returns
reliably. Code maps labels back.

**Instruction, in Thai:** group Needs that ask the graduate for the *same
capability* — one PLO could serve both without losing what either asked for.
Sharing a topic, a tool, or a source is not enough (the marketing/ethics pair
above shares 55% of its evidence). Each Need in at most one group; a group has
2–3 members of one KSEC tag; leaving every Need ungrouped is a valid answer and
the expected one for a well-separated set. One `reason_th` per group saying what
capability the members share.

**Output schema:**

```python
class _DuplicateGroup(BaseModel):
    labels: list[str]
    reason_th: str

class _DedupAnswer(BaseModel):
    groups: list[_DuplicateGroup] = []
```

Structural rules are *not* pydantic validators. A validator failure makes
instructor retry and then fail the call, which throws away every good group in
the answer for one bad one. The schema only has to parse; `accept_groups` judges.

`temperature=0`. One call per synthesis run, only when at least two in-scope
Needs exist. Not cached: it is one call, and a cache would need a contract
fingerprint for a prompt still being tuned.

## `accept_groups` — pure code

Takes the answer and the labelled Needs, returns the groups it accepts. Walks the
groups in answer order and **drops a whole group** — never trims it — when:

1. fewer than two distinct labels map to a known Need (unknown labels removed first);
2. any member is already in an accepted group (first group wins);
3. members span more than one KSEC tag — a K Need folded into an S sentence is
   the knowledge disappearing, and all four real pairs are same-tag anyway;
4. more than three members — the fifteen-name-group problem of ticket 18,
   one sentence that cannot carry everything it claims.

Trimming was rejected: which member to cut is exactly the judgement the model
was asked for, and code picking by position would make a decision nobody made.
Every dropped group is logged with its rule and its labels.

## Units and slot selection

A unit is an accepted group or a lone Need. For each unit:

- members ordered by `synthesis_order` (demand first), so the plural prompt
  lists the most-demanded Need first;
- `demand_score` of the unit = its top member's;
- `is_optional` = all members optional (the rule `validate_and_build` already
  applies, now also used to pick the series).

Slot selection runs today's algorithm over units instead of Needs: split by
`is_optional`, order by (−demand, first member's `need_id`), cap the core series
at `MAX_CORE_PLOS`, number from 1. A fold therefore frees a core slot and the
next unit below the cut takes it — the stage produces fewer duplicates, not
fewer PLOs, while there are Needs left to use.

## The floor: a separate, lower bound for merging

Folding lowers the number of distinct outcomes; on the stored run it would take
the core count from 8 to 5 or 6. The policy band stays 6-10 (`MIN_NEEDS`,
`MAX_CORE_PLOS`) and so does every warning built on it. Merging gets its own,
looser floor: **`MIN_CORE_AFTER_MERGE = 4`**, declared in `stages/need_grouping.py`
beside the other two bounds — one policy module, as rule 6 already says.

Two PLOs that say one thing are not two outcomes, so a merge is allowed to take
the set below 6. It is not allowed to take it below 4: at that point the set has
stopped looking like a programme's outcomes, and a model's grouping, or a hurried
click, should not be what gets it there. Between 4 and 5 the existing
core-below-`MIN_NEEDS` warning fires as it does today, and the dedupe step adds
one line naming how many core Needs it folded, so the designer can tell a
shortfall from duplicates apart from a shortfall from missing evidence.

**Automatic folds.** After `accept_groups`, slot selection runs with every
accepted group folded. If the core slot count is then below
`target = min(MIN_CORE_AFTER_MERGE, core slot count with no folds)`, the accepted
group with the **lowest top-member demand** that reduces the core count (it has
two or more core members) is unfolded, and selection runs again, until the
target is met or no such group is left. `min(...)` is the merge route's own
"only when this merge causes the shortfall" clause: a programme that has three
core Needs to begin with is not blocked, it simply gets no core folds. Lowest
demand goes first because the most-demanded outcomes are the ones the numbering
and the report lead with, and a fold there is the one most worth keeping. Each
unfold is logged with its labels and the reason `floor`.
(Below the floor every lowering fold is unfolded whichever way the target is
written, so the implementation loops against `MIN_CORE_AFTER_MERGE` directly.) Groups whose members
are all optional, or that fold an optional Need into a core one, never lower the
core count and are never unfolded for it. The ceiling is not something the step
checks: folds only lower the count, and slot selection still caps at
`MAX_CORE_PLOS` by choosing units.

**Manual merges.** `POST /plos/from-needs` checks its floor against
`MIN_CORE_AFTER_MERGE` instead of `MIN_NEEDS`, keeping the "only when this merge
causes it" clause and the `MAX_CORE_PLOS` ceiling as they are. Its Thai 422
message names 4. One floor for both paths, so a merge the step would have made
automatically is never refused by hand.

## Failure

Any exception from the call (endpoint down, instructor giving up, a timeout) is
logged as a warning and treated as "no groups". The step can only fold; its
absence is today's behaviour, so an outage costs duplicates, never a PLO.

## What the designer sees

No schema change and no migration. A folded PLO cites two or three Needs in
`source_need_ids`, and its trail carries all their evidence — visible on the PLO
page as it is for a manual merge. The reason for each fold is in the log.
Persisting `reason_th` on the PLO is left for later; it would need a field.

## Rule 6, amended

From "6-10 main PLOs per program, each drafted from one Need" to "each drafted
from one Need, **or from up to three same-KSEC Needs that the duplicate check
found to ask for one capability**", plus one sentence: merging — automatic or
through the merge route — may take the core count below 6 but not below
`MIN_CORE_AFTER_MERGE` (4), unless the set was already below it. The 6-10 band,
its warnings, and the rule that the ceiling is enforced by choosing units rather
than merging to fit a number are unchanged.

## Measurement before commit

A read-only probe over the 13 stored Needs (no DB writes), three runs:

- **must fold:** `252f`+`6a45` (with or without `d7c4`), `afe6`+`befb`,
  `5dd3`+`1b4f` — the latter only if `1b4f` is in scope;
- **must not fold:** `1fe0` (marketing) with `252f` or `afe6` — the
  high-evidence-overlap, different-capability pairs;
- stable across the three runs, or the instability recorded.

If the default model fails this, try the validation model (glm-5.3-flash) before
changing the prompt, and record the comparison.

Caveat recorded, not solved here: `252f` and `6a45` are `[ต้องทบทวน]` fallback
Needs — joined skill names, not sentences. The probe runs on them as stored. The
Bloom fix (`7d5d2a0`) also changes stored Needs only on a need_combination
re-run, so the end-to-end check is need_combination → plo_synthesis, run by the
designer after this lands.

## Tests

- `accept_groups`: each of the four drop rules, label mapping, unknown labels,
  first-group-wins, an empty answer.
- units and slot selection: a fold frees a slot the next Need fills; unit demand
  is the top member's; optional-with-core becomes core; two optionals stay
  optional; ceiling counts units; numbering stays demand order.
- floor: a fold that would leave 3 core slots is unfolded, lowest-demand group
  first; a set starting at 3 gets no core folds but keeps optional folds; an
  optional-into-core group is never unfolded for the floor; the result at
  exactly 4 is kept.
- merge route: a merge leaving 5 or 4 core PLOs succeeds; one leaving 3 from 4
  is refused with the Thai 422; on a set already at 3, a merge that does not
  lower the count (Needs nothing cites yet) still succeeds.
- `run`: kill switch makes no call; a raising call yields today's slots; fewer
  than two Needs makes no call; a folded slot's PLO cites every member.
- prompt builder: labels in demand order, KSEC tag and context line present,
  no `need_id` in the text.
- `test_llm_slots.py` walks the new `SlotSpec` without edits.
- Mutation pass on each drop rule, the unit demand rule, the floor, and
  the unfold order.

## Docs

`CLAUDE.md` (stack slot list, rule 6 including the merge route's floor, a pitfall on why evidence overlap is not
the similarity), `.env.example`, skill `references/prompts.md` (why the prompt
says what it says), `docs/prompt-inventory.md` via `scripts/dump_prompts.py`.
