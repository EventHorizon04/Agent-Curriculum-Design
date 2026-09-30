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

## The floor

Folding lowers the number of distinct outcomes, and on the stored run it will
likely take the core count from 8 to 5 or 6. The design accepts that and does
**not** refuse a fold to stay at `MIN_NEEDS`: two PLOs that say one thing are not
two outcomes, and keeping them to satisfy a count is the padding the band is
meant to expose. The existing core-below-floor warning fires as before; the
dedupe step adds one line naming how many core Needs it folded, so the designer
reading the shortfall can see it came from duplicates rather than from missing
evidence. The merge route's own floor check is unchanged — it guards a manual
action on a stored set, which is a different situation.

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
found to ask for one capability**". The ceiling is still enforced by choosing
units, not by merging to fit a number: the dedupe step never sees the ceiling.

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
- `run`: kill switch makes no call; a raising call yields today's slots; fewer
  than two Needs makes no call; a folded slot's PLO cites every member.
- prompt builder: labels in demand order, KSEC tag and context line present,
  no `need_id` in the text.
- `test_llm_slots.py` walks the new `SlotSpec` without edits.
- Mutation pass on each drop rule and on the unit demand rule.

## Docs

`CLAUDE.md` (stack slot list, rule 6, a pitfall on why evidence overlap is not
the similarity), `.env.example`, skill `references/prompts.md` (why the prompt
says what it says), `docs/prompt-inventory.md` via `scripts/dump_prompts.py`.
