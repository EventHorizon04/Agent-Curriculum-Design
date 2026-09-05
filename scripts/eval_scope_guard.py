"""Measure whether the scope guard keeps out-of-scope Needs out of PLO synthesis.

Run this by hand — when a prompt changes, when a model changes, when a slot moves
providers. Not in CI: it makes tens of real LLM calls per pass, and its output is
a judgement aid for a person, not a red/green gate. Commit the JSON it writes so
successive runs can be compared.

    uv run python scripts/eval_scope_guard.py --out .scratch/plo-scope-guard/eval

What it measures, and why at this level: the guard filters Needs, so the numbers
that decide whether a PLO escapes are Need-level ones. Skill-level recall flatters
the guard badly — an eight-member Need is only filtered when all eight of its
members are flagged — so those figures are reported as diagnostics beneath the
Need-level ones, never as the headline.

PLO level is deliberately not measured. A PLO escapes only if its Need did, and
synthesising them costs a model call each to learn nothing new.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from curriculum_agent.data.repositories import LLMCacheRepository
from curriculum_agent.llm import complete_extraction, describe_target
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    StakeholderType,
)
from curriculum_agent.prompts.extract_skills import build_extract_skills_prompt
from curriculum_agent.prompts.program_context import build_program_context_th
from curriculum_agent.stages.demand import build_scoring_corpus
from curriculum_agent.stages.need_combination import _build_groups
from curriculum_agent.stages.need_grouping import normalize_need_name
from curriculum_agent.stages.skill_extraction import (
    _compute_skill_importance,
    _ExtractedSkillsResponse,
    chunk_evidence_text,
    classify_skills,
)
from curriculum_agent.stages.stakeholder_needs import classify_evidence_type

# --------------------------------------------------------------------------
# The fixture: the one program with a human answer key
# --------------------------------------------------------------------------

# TCISM's own translation programme. The answer key is Needs_to_PLO_TCISM.xlsx —
# 13 Needs a person grouped into 4 themes and 4 PLOs by hand — which is what makes
# this case usable at all. A second real programme would need a second such key,
# and those cannot be commissioned on demand; the synthetic case below is how the
# other axis gets exercised without one.
PROGRAM = {
    "field": "การแปลและการล่ามภาษาจีน-ไทยเพื่อธุรกิจ",
    "name_th": "วิทยาลัยนานาชาติไทย-จีนเพื่อการจัดการ",
    "degree_level": "bachelor",
}

SCOPE_TH = (
    "หลักสูตรนี้ครอบคลุมการแปลเอกสารธุรกิจและกฎหมายจีน-ไทย การล่ามการเจรจาธุรกิจ "
    "การตรวจแก้งานแปลที่ได้จากเครื่อง (post-editing) และความรู้ด้านวัฒนธรรมและ"
    "มารยาททางธุรกิจจีนที่จำเป็นต่องานแปลและล่าม"
)

# Where the human's own decisions land on this corpus. CORE items are the ones
# whose skills the answer key kept; NOISE items are the two whose content it
# dropped — administrators and programme staff describing what the *institution*
# will do. Everything else is neither: institutional-direction evidence the key
# drew on selectively, which no per-item verdict describes honestly.
CORE_EVIDENCE = {"ev06", "ev07", "ev08", "ev09", "ev14"}
NOISE_EVIDENCE = {"ev10", "ev11"}

# Phrases that occur in SCOPE_TH and nowhere in the corpus. A skill whose name
# carries one was read out of the scope statement rather than out of evidence.
_SCOPE_PHRASES = (
    "แปลเอกสารธุรกิจ",
    "ล่ามการเจรจา",
    "ตรวจแก้งานแปล",
    "มารยาททางธุรกิจ",
    "post-editing",
)

# --------------------------------------------------------------------------
# Variants
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Variant:
    key: str
    scope_th: str
    note: str


# B0 — the pipeline before the second flag existed — is not run here. It cannot
# be: this working tree has the flag, and reproducing its absence would mean
# faking a response schema that no longer matches the prompt. Its numbers come
# from the file recorded before the change shipped, passed with --baseline.
VARIANTS = (
    Variant("B1", "", "flag present, no scope statement — isolates what the flag alone buys"),
    Variant("scoped", SCOPE_TH, "flag + scope statement — what a designer actually gets"),
)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


async def _extract_window(
    item: dict[str, Any],
    chunk: str,
    variant: Variant,
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """One extraction call, through the real prompt builder and the real schema.

    Deliberately not through skill_extraction.run: that writes to Postgres and
    reads the LLM cache, and a cached pass would measure the last run rather than
    this one.
    """
    messages = build_extract_skills_prompt(
        chunk,
        item["classification"],
        field_th=PROGRAM["field"],
        program_name_th=PROGRAM["name_th"],
        scope_th=variant.scope_th,
    )
    async with sem:
        try:
            result = await complete_extraction(_ExtractedSkillsResponse, messages)
        except Exception as exc:  # noqa: BLE001 — one bad call must not lose the pass
            logger.error(f"{variant.key} {item['evidence_id']}: {exc!r}")
            return []
    return [
        {
            **skill.model_dump(mode="json"),
            "evidence_id": item["evidence_id"],
            "stakeholder_type": item["stakeholder_type"],
        }
        for skill in result.skills
    ]


async def extract_corpus(evidence: list[dict[str, Any]], variant: Variant) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(6)
    tasks = [
        _extract_window(item, chunk, variant, sem)
        for item in evidence
        for chunk in chunk_evidence_text(item["raw_text_th"])[0]
    ]
    logger.info(f"{variant.key}: {len(tasks)} extraction calls")
    return [row for batch in await asyncio.gather(*tasks) for row in batch]


def to_skills(raw: list[dict[str, Any]], program_id: str) -> list[ExtractedSkill]:
    """Same assembly skill_extraction.run performs, minus the database."""
    evidence_class = {
        r["evidence_id"]: classify_evidence_type(StakeholderType(r["stakeholder_type"]))
        for r in raw
    }
    class_by_name = classify_skills(raw, evidence_class)
    class_by_norm = {normalize_need_name(k): v for k, v in class_by_name.items()}
    corpus = build_scoring_corpus((r["evidence_id"], r["stakeholder_type"]) for r in raw)
    importance = _compute_skill_importance(raw, corpus)

    skills: list[ExtractedSkill] = []
    for index, row in enumerate(raw):
        norm = normalize_need_name(row["skill_name_th"])
        skills.append(
            ExtractedSkill(
                skill_id=f"{program_id}-s{index}",
                program_id=program_id,
                skill_name_th=row["skill_name_th"],
                skill_name_en=row.get("skill_name_en"),
                ksec_category=KSECCategory(row["ksec_category"]),
                bloom_level=BloomLevel(row["bloom_level"]),
                evidence_span_th=row["evidence_span_th"],
                source_evidence_id=row["evidence_id"],
                source_stakeholder_type=StakeholderType(row["stakeholder_type"]),
                classification=class_by_norm.get(norm, "unclassified"),
                is_field_relevant=bool(row.get("is_field_relevant", True)),
                is_graduate_capability=bool(row.get("is_graduate_capability", True)),
                extraction_method="llm",
                confidence=row.get("confidence", 0.8),
                importance_score=importance.get(norm, 0.0),
            )
        )
    return skills


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


@dataclass
class Counts:
    total: int = 0
    filtered: int = 0
    off_field: int = 0
    off_grad: int = 0
    examples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "filtered": self.filtered,
            "off_field": self.off_field,
            "off_grad": self.off_grad,
            "examples": self.examples[:8],
        }


def _verdict(evidence_ids: set[str], injected: set[str]) -> str:
    """Ground truth for one Need, from where its members came from.

    A Need holding even one in-scope member is in scope: filtering it costs a real
    capability, whatever else it also holds. Only a Need built entirely out of
    material the answer key dropped — or entirely out of another field's postings —
    is one the guard should catch.
    """
    if injected and evidence_ids <= injected:
        return "out_of_scope"
    if evidence_ids & CORE_EVIDENCE:
        return "in_scope"
    if evidence_ids and evidence_ids <= NOISE_EVIDENCE:
        return "out_of_scope"
    return "unlabelled"


def score_needs(groups: list[Any], injected: set[str]) -> dict[str, Any]:
    buckets = {name: Counts() for name in ("in_scope", "out_of_scope", "unlabelled")}
    mandated_and_filtered: list[str] = []

    for group in groups:
        in_field = group.in_field_skill_count > 0
        is_grad = group.graduate_capability_skill_count > 0
        filtered = not (in_field and is_grad)
        bucket = buckets[_verdict(set(group.evidence_ids), injected)]
        bucket.total += 1
        if filtered:
            bucket.filtered += 1
            bucket.off_field += int(not in_field)
            bucket.off_grad += int(not is_grad)
            bucket.examples.append(", ".join(group.skill_names[:3]))
            # `classification` never reaches is_in_scope, so a professional
            # council's own mandate is filtered exactly like anything else. That
            # is worth seeing rather than assuming: a filtered mandate is a
            # legally required capability the pipeline dropped on a model's word.
            if group.classification_coverage.get("requirement"):
                mandated_and_filtered.append(", ".join(group.skill_names[:3]))

    return {
        "in_scope": buckets["in_scope"].as_dict(),
        "out_of_scope": buckets["out_of_scope"].as_dict(),
        "unlabelled": buckets["unlabelled"].as_dict(),
        "false_positives": buckets["in_scope"].filtered,
        "recall": (
            buckets["out_of_scope"].filtered / buckets["out_of_scope"].total
            if buckets["out_of_scope"].total
            else None
        ),
        "mandated_but_filtered": mandated_and_filtered,
    }


def score_skills(raw: list[dict[str, Any]], injected: set[str]) -> dict[str, Any]:
    """Diagnostics: the per-skill figures that explain the Need-level ones.

    Includes the 2x2 between the axes. The two have so far agreed on every skill,
    which is the number that decides whether keeping two columns is still earning
    its keep — the day it stops being 100% is the day they measure different
    things.
    """
    cells = {"both_off": 0, "field_only": 0, "grad_only": 0, "neither": 0}
    core = {"total": 0, "flagged": 0}
    noise = {"total": 0, "flagged": 0}

    for row in raw:
        field_off = row.get("is_field_relevant", True) is False
        grad_off = row.get("is_graduate_capability", True) is False
        key = (
            "both_off"
            if field_off and grad_off
            else "field_only"
            if field_off
            else "grad_only"
            if grad_off
            else "neither"
        )
        cells[key] += 1

        eid = row["evidence_id"]
        target = core if eid in CORE_EVIDENCE else noise if eid in NOISE_EVIDENCE else None
        if eid in injected:
            target = noise
        if target is not None:
            target["total"] += 1
            target["flagged"] += int(field_off or grad_off)

    return {"overlap": cells, "core": core, "noise": noise, "total": len(raw)}


def score_contamination(
    raw: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    """Skills read out of the scope statement instead of out of the evidence.

    Kept as a standing metric rather than a one-off check: the position that
    stopped it was verified against a ~150-character statement, and nobody knows
    where a longer one starts leaking again. A skill counted here is one whose
    evidence_span_th cannot be pointing at real evidence.
    """
    body = {e["evidence_id"]: "".join(e["raw_text_th"].split()) for e in evidence}
    named: list[str] = []
    ungrounded: list[str] = []
    for row in raw:
        if any(phrase in row["skill_name_th"] for phrase in _SCOPE_PHRASES):
            named.append(f"{row['evidence_id']}  {row['skill_name_th']}")
        span = "".join(str(row["evidence_span_th"]).split())
        if span not in body.get(row["evidence_id"], ""):
            ungrounded.append(f"{row['evidence_id']}  {row['skill_name_th']}")
    return {
        "scope_named": len(named),
        "scope_named_examples": named[:8],
        "ungrounded_spans": len(ungrounded),
        "ungrounded_examples": ungrounded[:8],
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def render(results: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    lines: list[str] = []
    w = lines.append

    for case_name, case in results.items():
        w(f"=== case: {case_name}")
        w("")
        w(f"{'variant':10s} {'FP (in-scope filtered)':>24s} {'recall (out-of-scope)':>23s}")
        for variant, data in case.items():
            need = data["needs"]
            recall = need["recall"]
            hit = f"{need['out_of_scope']['filtered']}/{need['out_of_scope']['total']}"
            recall_txt = "—" if recall is None else f"{hit} ({recall:.0%})"
            fp = f"{need['false_positives']}/{need['in_scope']['total']}"
            w(f"{variant:10s} {fp:>24s} {recall_txt:>23s}")
        w("")

        for variant, data in case.items():
            need, skill, contam = data["needs"], data["skills"], data["contamination"]
            w(f"--- {variant}")
            labelled = ("in_scope", "out_of_scope", "unlabelled")
            w(
                f"    Need ทั้งหมด {sum(need[k]['total'] for k in labelled)}"
                f" · ในขอบเขต {need['in_scope']['total']}"
                f" · นอกขอบเขต {need['out_of_scope']['total']}"
                f" · ไม่มีเฉลย {need['unlabelled']['total']}"
            )
            w(f"    skill: {skill['total']} · overlap {skill['overlap']}")
            w(
                f"    contamination: ชื่อลอกจาก scope {contam['scope_named']}"
                f" · span หาไม่พบ {contam['ungrounded_spans']}"
            )
            if need["mandated_but_filtered"]:
                w(
                    f"    ⚠ Need ที่ถูกกรองทั้งที่มีสมาชิกเป็น requirement: "
                    f"{len(need['mandated_but_filtered'])}"
                )
                for example in need["mandated_but_filtered"][:5]:
                    w(f"        {example}")
                w(
                    "      `requirement` ไม่ได้ปกป้อง Need จากการกรอง — มันตัดสิน "
                    "`classification` เท่านั้น ส่วน is_in_scope อ่านธงดิบ"
                )
            if need["in_scope"]["filtered"]:
                w("    ⚠ FALSE POSITIVE — เกณฑ์ผ่านคือศูนย์:")
                for example in need["in_scope"]["examples"]:
                    w(f"        {example}")
            w("")

    if baseline is not None:
        w("=== B0 (จากไฟล์ ก่อนธงแกนที่สอง)")
        w(f"    {json.dumps(baseline, ensure_ascii=False)[:400]}")
        w("    B1 − B0 = ช่องธงที่สองให้อะไร · scoped − B1 = scope statement ให้อะไร")
        w("")

    w("เกณฑ์: false positive ที่ระดับ Need = 0 เป็น hard gate; recall เป็นตัวเลขรายงาน")
    w("ไม่ใช่ gate — Need ในขอบเขตที่ถูกกรองผิดคือ PLO ที่หายไปโดยไม่มีใครรู้ ส่วน Need")
    w("นอกขอบเขตที่หลุดมา designer ลบได้ที่ checkpoint")
    return "\n".join(lines)


# --------------------------------------------------------------------------


def load_injected(csv_path: Path, count: int) -> list[dict[str, Any]]:
    """Job postings from another field entirely, as evidence items.

    Their verdict needs no rubric and no judge: a nursing posting in a translation
    programme is out of scope by construction. Half arrive as `employer` and half
    as `professional_council`, because the two are treated differently by
    classification and the report has to separate them.
    """
    import csv

    if not csv_path.exists():
        logger.warning(f"{csv_path} not found — running the TCISM-only case")
        return []

    rows: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8", errors="replace") as handle:
        for record in csv.DictReader(handle):
            # Column names as the scraper wrote them, not as they read: "Title"
            # is capitalised and the body is "job description" with a space.
            text = " ".join(
                str(record.get(key, ""))
                for key in ("Title", "job description", "skills")
                if record.get(key)
            ).strip()
            if len(text) < 200:
                continue
            index = len(rows)
            stakeholder = "employer" if index % 2 == 0 else "professional_council"
            rows.append(
                {
                    "evidence_id": f"inj{index:02d}",
                    "stakeholder_type": stakeholder,
                    "raw_text_th": text[:1500],
                    "classification": classify_evidence_type(StakeholderType(stakeholder)),
                }
            )
            if len(rows) >= count:
                break
    return rows


@contextlib.contextmanager
def in_memory_llm_cache() -> Iterator[None]:
    """Keep the clustering call off Postgres for the length of an eval run.

    Two reasons, and only one of them is convenience. A stored entry would replay
    a previous run's grouping, so the pass would report numbers the current prompt
    never produced; and requiring a database to measure prompt behaviour would make
    this script unrunnable exactly when it is most wanted — on a laptop, against a
    prompt someone is in the middle of editing. Within one run the memo still holds,
    so the two variants do not re-cluster identical input.
    """
    store: dict[str, tuple[str, str]] = {}

    async def get(_self: Any, key: str) -> tuple[str, str] | None:
        return store.get(key)

    async def put(_self: Any, key: str, model: str, payload: str, **_: Any) -> None:
        store[key] = (model, payload)

    original_get, original_set = LLMCacheRepository.get, LLMCacheRepository.set
    LLMCacheRepository.get, LLMCacheRepository.set = get, put  # type: ignore[method-assign]
    try:
        yield
    finally:
        LLMCacheRepository.get, LLMCacheRepository.set = original_get, original_set  # type: ignore[method-assign]


async def run_case(
    name: str, evidence: list[dict[str, Any]], injected_ids: set[str]
) -> dict[str, Any]:
    context = build_program_context_th(PROGRAM)
    out: dict[str, Any] = {}
    for variant in VARIANTS:
        raw = await extract_corpus(evidence, variant)
        if not raw:
            logger.error(f"{name}/{variant.key}: no skills extracted — skipping")
            continue
        skills = to_skills(raw, f"eval-{name}-{variant.key}")
        stakeholder_by_evidence = {
            item["evidence_id"]: item["stakeholder_type"] for item in evidence
        }
        groups = await _build_groups(skills, stakeholder_by_evidence, context)
        out[variant.key] = {
            "note": variant.note,
            "needs": score_needs(groups, injected_ids),
            "skills": score_skills(raw, injected_ids),
            "contamination": score_contamination(raw, evidence),
        }
    return out


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path(".scratch/plo-scope-guard/eval/baseline/evidence.json"),
        help="the split TCISM corpus",
    )
    parser.add_argument(
        "--postings",
        type=Path,
        default=Path("Data/linkedin_offers2026-04-30.csv"),
        help="source of the out-of-field postings for the synthetic case",
    )
    parser.add_argument("--inject", type=int, default=6, help="how many postings to inject")
    parser.add_argument("--baseline", type=Path, help="B0 results recorded before the flag shipped")
    parser.add_argument("--out", type=Path, default=Path(".scratch/plo-scope-guard/eval"))
    args = parser.parse_args()

    if not args.evidence.exists():
        logger.error(f"{args.evidence} not found")
        return 1

    logger.info(describe_target())
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    injected = load_injected(args.postings, args.inject)

    with in_memory_llm_cache():
        results = {"tcism": await run_case("tcism", evidence, set())}
        if injected:
            injected_ids = {item["evidence_id"] for item in injected}
            results["tcism+injected"] = await run_case(
                "tcism+injected", evidence + injected, injected_ids
            )

    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = render(results, baseline)
    (args.out / "report.txt").write_text(report, encoding="utf-8")
    # A Windows console defaults to cp1252 and cannot encode Thai; the report is
    # mostly Thai, so printing it raw kills the run after every call has been paid
    # for. The file is the artefact either way.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(report)

    # Exit code reports the hard gate, but nothing is wired to act on it: this is
    # run by a person reading the report, not by a pipeline gating a merge.
    failures = sum(
        variant["needs"]["false_positives"]
        for case in results.values()
        for variant in case.values()
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
