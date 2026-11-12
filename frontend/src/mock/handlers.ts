/**
 * Every endpoint the frontend calls, answered from the mock database.
 *
 * Each handler is written against its FastAPI route in
 * src/curriculum_agent/api/routes/ — same status codes, same Thai `detail`
 * where the route refuses, same response model. Where the real route calls an
 * LLM, the mock substitutes the builders in scenarios.ts; the pure-code parts
 * (classification, demand, the SMART hard gate, the 6-10 band) are mirrored.
 */
import type { JobInfo, JobKind } from '../api/jobs'
import type { JobUsage, SessionUsage, SlotUsage, UsageSummary, UsageTotals } from '../api/usage'
import type { SMARTCheck, SmartFinding } from '../types/plo'
import type { FeedbackAction, PLOSetReview } from '../types/ploReview'
import { MAX_CORE_PLOS, MAX_MERGE_NEEDS, fallbackKind } from '../constants/needPolicy'
import { scopeVerdict } from '../constants/scope'
import {
  clone,
  consumeFailNextRun,
  getControls,
  getDb,
  newId,
  nowIso,
  saveDb,
  utcIso,
  type EvidenceRow,
  type NeedRow,
  type PloRow,
  type ProgramRow,
  type SessionRow,
} from './db'
import { Router, detail, ok, type MockRequest, type MockResponse } from './router'
import {
  BLOOM_LEVELS,
  CHECKPOINTS,
  INTERRUPT_MESSAGE,
  STAKEHOLDER_TYPES,
  activeNeeds,
  classifyEvidence,
  combineNeeds,
  extractSkills,
  buildMockReview,
  formatPloId,
  makePlo,
  mergedPloSeed,
  passingCheck,
  skillGroupsOf,
  sortNeeds,
  sortPlos,
  stripOutcomePrefix,
  synthesizePlos,
} from './scenarios'
import { XLSX_TYPE, buildXlsx } from './xlsx'

/** MIN_CORE_AFTER_MERGE in need_grouping.py. */
const MIN_CORE_AFTER_MERGE = 4

// ----------------------------------------------------------------------------
// Latency
// ----------------------------------------------------------------------------

function between(min: number, max: number): number {
  return Math.round(min + Math.random() * (max - min))
}

export function latencyFor(speed: 'normal' | 'slow'): number {
  if (!getControls().latency) return 0
  return speed === 'slow' ? between(2000, 4000) : between(300, 900)
}

export function pause(ms: number): Promise<void> {
  return ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve()
}

/** What a run ends with when "run ถัดไปล้มเหลว" is armed: the job's `error_th`,
 *  as the runner records an exception the stage raised. The text is the mock's. */
function runFailureText(stage: string): string {
  return `mock: จำลองการรัน ${stage} ล้มเหลว — เรียกโมเดลไม่สำเร็จ (หมดเวลารอ 300 วินาที)`
}

// ----------------------------------------------------------------------------
// Lookups
// ----------------------------------------------------------------------------

function findProgram(pid: string): ProgramRow | undefined {
  return getDb().programs.find((p) => p.program_id === pid)
}

const of = <T extends { program_id: string }>(rows: T[], pid: string): T[] =>
  rows.filter((r) => r.program_id === pid)

function replaceRows(table: 'skills' | 'needs' | 'plos', pid: string, rows: { program_id: string }[]): void {
  const db = getDb() as unknown as Record<string, { program_id: string }[]>
  db[table] = [...db[table].filter((r) => r.program_id !== pid), ...rows]
}

function body<T>(req: MockRequest): Partial<T> {
  return (req.body && typeof req.body === 'object' ? req.body : {}) as Partial<T>
}

/** FastAPI's 422 for a body that fails validation. */
function invalid(errors: { loc: string[]; msg: string; type: string }[]): MockResponse {
  return { status: 422, data: { detail: errors.map((e) => ({ ...e, input: null })) } }
}

// ----------------------------------------------------------------------------
// Programs
// ----------------------------------------------------------------------------

/** graph.stage_reached: derived from what is stored, never recorded. */
function stageReached(pid: string): string {
  const db = getDb()
  // graph.stage_reached: a stored review counts once the program has PLOs; the
  // mock never reports one stale, so any stored review is current.
  if (of(db.plos, pid).length && (db.reports ?? []).some((x) => x.program_id === pid)) {
    return 'plo_report'
  }
  if (of(db.plos, pid).length && (db.reviews ?? []).some((x) => x.program_id === pid)) {
    return 'plo_review'
  }
  if (of(db.plos, pid).length) return 'plo_synthesis'
  if (of(db.needs, pid).length) return 'need_analysis'
  if (of(db.skills, pid).length) return 'skill_extraction'
  if (of(db.evidence, pid).length) return 'stakeholder_needs'
  return 'intake'
}

function latestSession(pid: string): SessionRow | undefined {
  return of(getDb().sessions, pid).sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
}

function slugify(text: string): string {
  return text.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'program'
}

const PROGRAM_FIELDS = [
  'name_th',
  'name_en',
  'field',
  'isced_code',
  'degree_level',
  'duration_years',
  'faculty',
  'university',
  'scope_th',
  'professional_council',
  'accreditation_body',
  'subject_benchmark_ref',
  'program_objectives_th',
  'program_goals_th',
] as const

/** ProgramCreateRequest, validated the way Pydantic would. */
function parseProgram(req: MockRequest): Omit<ProgramRow, 'program_id' | 'created_at'> | MockResponse {
  const b = body<ProgramRow>(req)
  const errors: { loc: string[]; msg: string; type: string }[] = []
  for (const key of ['field', 'faculty', 'university'] as const) {
    if (typeof b[key] !== 'string') errors.push({ loc: ['body', key], msg: 'Field required', type: 'missing' })
  }
  if (!['bachelor', 'master', 'doctoral'].includes(String(b.degree_level))) {
    errors.push({
      loc: ['body', 'degree_level'],
      msg: "Input should be 'bachelor', 'master' or 'doctoral'",
      type: 'literal_error',
    })
  }
  const years = Number(b.duration_years)
  if (!Number.isInteger(years) || years < 1 || years > 8) {
    errors.push({
      loc: ['body', 'duration_years'],
      msg: years < 1 ? 'Input should be greater than or equal to 1' : 'Input should be less than or equal to 8',
      type: years < 1 ? 'greater_than_equal' : 'less_than_equal',
    })
  }
  if (errors.length) return invalid(errors)
  const out: Record<string, unknown> = {
    name_th: '',
    name_en: '',
    isced_code: null,
    scope_th: '',
    professional_council: null,
    accreditation_body: null,
    subject_benchmark_ref: null,
    program_objectives_th: [],
    program_goals_th: [],
  }
  for (const key of PROGRAM_FIELDS) if (b[key] !== undefined) out[key] = b[key]
  out.duration_years = years
  return out as Omit<ProgramRow, 'program_id' | 'created_at'>
}

function isResponse(value: unknown): value is MockResponse {
  return typeof value === 'object' && value !== null && 'status' in value && typeof (value as MockResponse).status === 'number'
}

// ----------------------------------------------------------------------------
// SMART hard gate (smart_rules.hard_failures + smart_vocabulary)
// ----------------------------------------------------------------------------

const FORBIDDEN_WORDS = ['รู้', 'จำ', 'เข้าใจ', 'ซาบซึ้ง', 'ตระหนัก', 'ศรัทธา', 'รัก']
const ALLOWED_COMPOUNDS = [
  'รักษา', 'การรักษา', 'รักษาการ', 'อนุรักษ์',
  'จำแนก', 'จำลอง', 'จำกัด', 'จำเป็น', 'จำนวน', 'จำหน่าย', 'จำเพาะ', 'ประจำ',
  'ความรู้', 'เรียนรู้', 'รู้จัก', 'ผู้รู้', 'รู้เท่าทัน',
]

function forbiddenWordsIn(statement: string): string[] {
  let masked = statement
  for (const allowed of [...ALLOWED_COMPOUNDS].sort((a, b) => b.length - a.length)) {
    masked = masked.split(allowed).join(' '.repeat(allowed.length))
  }
  return FORBIDDEN_WORDS.filter((w) => masked.includes(w))
}

const HARD_HINTS: Record<string, string> = {
  S_verb:
    'Specific ไม่ผ่าน: statement_th ต้องขึ้นต้นด้วย action_verb_th ซึ่งเป็นกริยาของผลลัพธ์หลัก ไม่ใช่กริยาในวลีรองอย่าง \'โดยใช้...\' หรือ \'เพื่อ...\' ถ้างานหลักของประโยคคือกริยาอื่น ให้เปลี่ยน action_verb_th เป็นกริยานั้น หรือเรียบเรียงประโยคใหม่',
  S_multi_verb:
    "Specific ไม่ผ่าน: action_verb_th ต้องเป็นกริยา Bloom เพียงตัวเดียว ใช้สองตัวได้เฉพาะเมื่ออยู่ระดับ Bloom เดียวกันหรือติดกัน เช่น 'ออกแบบและพัฒนา' (create ทั้งคู่) ใช้ได้ แต่ 'ออกแบบและดำเนินการ' (create กับ apply) ห่างกันเกินไป ให้เลือกตัวที่เป็นผลลัพธ์จริง",
  M_forbidden:
    'Measurable ไม่ผ่าน: ห้ามใช้คำ รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก ให้แทนด้วยกริยาที่สังเกตได้ เช่น อธิบาย วิเคราะห์ ออกแบบ (คำที่มีคำห้ามอยู่ข้างในแต่ใช้ได้ เช่น จำแนก จำลอง รักษา ความรู้ เรียนรู้)',
  R_evidence:
    'Relevant ไม่ผ่าน: source_need_ids ทุกรายการต้องอ้างอิง Need ที่มีอยู่จริง (ห้ามมี id ที่ไม่รู้จักแม้แต่รายการเดียว) และต้องมีอย่างน้อย 1 รายการ',
}

/** Simplification: S_multi_verb fires on any declared phrase joined by "และ".
 *  The real check consults the Bloom table and passes adjacent levels. */
function hardFailures(statement: string, verb: string, needIds: string[], known: Set<string>): string[] {
  const fails: string[] = []
  if (!verb || !stripOutcomePrefix(statement).startsWith(verb)) fails.push('S_verb')
  if (/\S+และ\S+/.test(verb)) fails.push('S_multi_verb')
  if (forbiddenWordsIn(statement).length) fails.push('M_forbidden')
  if (!needIds.length || !needIds.every((id) => known.has(id))) fails.push('R_evidence')
  return fails
}

function hardFindings(fails: string[]): SmartFinding[] {
  return fails.map((code) => ({ criterion: code, severity: 'hard' as const, note_th: HARD_HINTS[code] }))
}

function codeVerdict(fails: string[]): SMARTCheck {
  return {
    specific: !fails.includes('S_verb') && !fails.includes('S_multi_verb'),
    measurable: !fails.includes('M_forbidden'),
    achievable: true,
    relevant: !fails.includes('R_evidence'),
    timely: true,
    notes_th: null,
    findings: hardFindings(fails),
  }
}

// ----------------------------------------------------------------------------
// Sessions: the graph, simulated
// ----------------------------------------------------------------------------

function stepDuration(): number {
  return getControls().latency ? between(3000, 4500) : 800
}

type SessionInfo = Pick<
  SessionRow,
  'session_id' | 'program_id' | 'thread_id' | 'status' | 'current_stage' | 'suspended_message' | 'created_at' | 'updated_at'
>

/** SessionInfo — the row without the simulation's bookkeeping. */
function publicSession(s: SessionRow): SessionInfo {
  return {
    session_id: s.session_id,
    program_id: s.program_id,
    thread_id: s.thread_id,
    status: s.status,
    current_stage: s.current_stage,
    suspended_message: s.suspended_message,
    created_at: s.created_at,
    updated_at: s.updated_at,
  }
}

/** What one stage writes when a session runs it. Throws the stage's own error. */
function runStageForSession(pid: string, stage: string): void {
  const db = getDb()
  switch (stage) {
    case 'stakeholder_needs': {
      const evidence = of(db.evidence, pid)
      if (!evidence.length) {
        throw new Error('ไม่มี evidence สำหรับโปรแกรมนี้ กรุณาเพิ่ม evidence ที่ขั้น Stakeholder Needs ก่อน')
      }
      for (const e of evidence) e.classification = classifyEvidence(e.stakeholder_type)
      return
    }
    case 'need_analysis': {
      // Agent 1 then Agent 2, back to back; the gate is after Agent 2.
      const { skills } = extractSkills(pid, of(db.evidence, pid))
      if (!skills.length) throw new Error('ไม่มีทักษะที่สกัดได้จาก evidence ของโปรแกรมนี้')
      replaceRows('skills', pid, skills)
      replaceRows('needs', pid, combineNeeds(pid, skills))
      return
    }
    case 'plo_synthesis': {
      const needs = activeNeeds(of(db.needs, pid))
      if (!needs.length) throw new Error('ไม่มี Needs สำหรับโปรแกรมนี้ กรุณารัน Need Combination ก่อน')
      replaceRows('plos', pid, synthesizePlos(pid, needs, of(db.skills, pid)))
      // A fresh synthesis wipes the history too, as POST /plos/run does.
      db.superseded = (db.superseded ?? []).filter((x) => x.program_id !== pid)
      db.feedback = (db.feedback ?? []).filter((x) => x.program_id !== pid)
      return
    }
  }
}

/** The report body, built from the set as it is now: active Needs only, like the
 *  real report, since merged-away originals are stored but nothing reads them. */
function buildReport(pid: string) {
  const plos = sortPlos(of(getDb().plos, pid))
  const needs = activeNeeds(of(getDb().needs, pid))
  const cited = new Set(plos.flatMap((p) => p.source_need_ids))
  const notSynthesized = needs.map((n) => n.need_id).filter((id) => !cited.has(id))
  // Excluded by the designer; a merged-away original is a fold, not an exclusion.
  const excluded = of(getDb().needs, pid)
    .filter((n) => n.excluded_at !== null && n.merged_into === null)
    .sort((a, b) => (a.excluded_at as string).localeCompare(b.excluded_at as string) || a.need_id.localeCompare(b.need_id))
    .map((n) => ({
      need_id: n.need_id,
      statement_th: n.statement_th,
      ksec_categories: n.ksec_categories,
      demand_score: n.demand_score,
      excluded_at: n.excluded_at,
    }))
  const core = plos.filter((p) => !p.is_optional).length
  return {
    plos,
    counts: {
      total: plos.length,
      core,
      optional: plos.length - core,
      escalated: plos.filter((p) => p.smart_escalated).length,
      stale: plos.filter((p) => p.smart_validated_by === 'stale').length,
      code_only: plos.filter((p) => p.smart_validated_by === 'code_only').length,
      needs_not_synthesized: notSynthesized.length,
      needs_excluded: excluded.length,
    },
    needs_by_id: Object.fromEntries(needs.map((n) => [n.need_id, n])),
    needs_not_synthesized: notSynthesized,
    needs_excluded: excluded,
  }
}

/** Stores the report, replacing the previous one — the designer's approval. */
function storeReport(pid: string): ReturnType<typeof buildReport> {
  const db = getDb()
  const report = clone(buildReport(pid))
  db.reports = [...(db.reports ?? []).filter((x) => x.program_id !== pid), { program_id: pid, created_at: utcIso(), report }]
  return report
}

/** What resuming the last checkpoint runs: plo_report, then plo_review, then END.
 *  The review is stored the way the real graph's plo_review node stores it. */
function finishSession(pid: string): void {
  const db = getDb()
  const plos = of(db.plos, pid)
  if (!plos.length) {
    throw new Error(`PLO report: no PLOs for program '${pid}' — run PLO synthesis first`)
  }
  const degree = db.programs.find((p) => p.program_id === pid)?.degree_level ?? 'bachelor'
  const review = buildMockReview(pid, plos, of(db.needs, pid), degree)
  db.reviews = [...(db.reviews ?? []).filter((x) => x.program_id !== pid), review]
  sendBack(pid, review)
  // The review comes first now and the report last, so the stored report
  // describes the set the send-back left.
  storeReport(pid)
}

/** Replace every outcome citing one of the selected Needs with one drafted from
 *  them, numbered from what survives, and keep what it replaced. The core of
 *  POST /plos/from-needs, shared with the review's send-back; the caller has
 *  already checked the bounds. */
function replaceFromNeeds(pid: string, selected: NeedRow[], cause: 'designer' | 'review'): PloRow {
  const db = getDb()
  const needIds = selected.map((n) => n.need_id)
  const isOptional = selected.every((n) => n.is_optional)
  const existing = of(db.plos, pid)
  const superseded = existing.filter((p) => p.source_need_ids.some((id) => needIds.includes(id)))
  const supersededIds = new Set(superseded.map((p) => p.plo_id))
  const surviving = existing.filter((p) => !supersededIds.has(p.plo_id))
  // Numbered from what survives, so the merge reuses the lowest freed slot.
  const prefix = isOptional ? 'OPT' : 'PLO'
  const used = new Set(
    surviving
      .map((p) => p.plo_id)
      .filter((id) => id.startsWith(prefix) && /^\d+$/.test(id.slice(prefix.length)))
      .map((id) => Number(id.slice(prefix.length))),
  )
  let index = 1
  while (used.has(index)) index++
  const plo = makePlo(pid, formatPloId(index, isOptional), selected, mergedPloSeed(selected, of(db.skills, pid)), isOptional)
  db.plos = [...db.plos.filter((p) => !(p.program_id === pid && supersededIds.has(p.plo_id))), plo]
  // The replaced outcomes are kept, the way the server snapshots them.
  const at = new Date().toISOString().replace('Z', '+00:00')
  db.superseded = [
    ...(db.superseded ?? []),
    ...superseded.map((old) => ({
      id: `${pid}:${old.plo_id}:${at}`,
      program_id: pid,
      superseded_by: plo.plo_id,
      superseded_at: at,
      cause,
      plo: old,
    })),
  ]
  return plo
}

/** The review's send-back as the server's loop runs it in apply mode, two rounds
 *  long: round 1 redrafts the last core PLO for an agreed alignment finding and
 *  records the unused Need it cannot draft; round 2 reads the new set, finds
 *  nothing to fix and writes the `loop_end` row. The stored review is round 2's.
 *  A code-only review sends nothing back. */
function sendBack(pid: string, review: PLOSetReview): FeedbackAction[] {
  if (review.reviewed_by !== 'agent') return []
  const db = getDb()
  const stamp = (t: number): string => new Date(t).toISOString().replace('Z', '+00:00')
  // The review's own timestamp is naive; the trail's carries the offset.
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(review.created_at)
  const round1At = hasZone ? review.created_at : `${review.created_at}+00:00`
  const rows: FeedbackAction[] = []
  // One row per action, written right after it: each gets its own instant, so
  // the newest-first list reads in reverse action order like the server's.
  const base = Date.now()
  const push = (
    r: Pick<FeedbackAction, 'kind' | 'plo_ids' | 'need_ids' | 'finding_reason_th' | 'instruction_th' | 'outcome' | 'outcome_reason_th'> &
      Partial<FeedbackAction>,
    round: number,
    reviewAt: string,
  ): void => {
    rows.push({
      result_plo_id: null,
      result_statement_th: null,
      result_bloom_level: null,
      ...r,
      id: newId(),
      program_id: pid,
      review_created_at: reviewAt,
      round,
      created_at: new Date(base + rows.length).toISOString(),
    })
  }

  // Round 1
  const target = of(db.plos, pid)
    .filter((p) => !p.is_optional)
    .at(-1)
  const needById = new Map(of(db.needs, pid).map((n) => [n.need_id, n]))
  const needs = (target?.source_need_ids ?? []).map((id) => needById.get(id)).filter((n): n is NeedRow => !!n)
  if (target && needs.length > 0) {
    const reason = 'ข้อความ PLO ยังไม่ตอบงานที่ Need ต้นทางขอไว้ครบ'
    const plo = replaceFromNeeds(pid, needs, 'review')
    push(
      {
        kind: 'alignment',
        plo_ids: [target.plo_id],
        need_ids: needs.map((n) => n.need_id),
        finding_reason_th: reason,
        instruction_th: 'ร่างใหม่ให้ตอบงานที่ Need ระบุ',
        outcome: 'applied',
        outcome_reason_th: '',
        result_plo_id: plo.plo_id,
        result_statement_th: plo.statement_th,
        result_bloom_level: plo.bloom_level,
      },
      1,
      round1At,
    )
  }
  const unused = review.unused_needs.find((n) => n.verdict === 'consider')
  if (unused) {
    push(
      {
        kind: 'unused_need',
        plo_ids: [],
        need_ids: [unused.need_id],
        finding_reason_th: unused.reason_th,
        instruction_th: '',
        outcome: 'skipped',
        outcome_reason_th: 'ร่างใหม่ไม่ผ่าน SMART — คงข้อเดิมไว้',
      },
      1,
      round1At,
    )
  }

  // Round 2 reads the set round 1 left; its review is the stored one, made after
  // the replacement so the replaced outcome's snapshot falls inside round 1.
  // Deliberate mutation: `review` is the object already stored in db.reviews, so
  // this re-stamps the stored review as round 2's (the final review of the job).
  review.created_at = new Date(Date.now() + 1).toISOString().replace('Z', '')
  // Round 2 stops as a pass, so it found no agreed redundancy, Bloom or unused-Need
  // finding (the real `has_agreed_work` counts all three): the scenario's are what
  // the loop acted on, and the review it stored is the one read after. They stay as
  // findings below the threshold, like the real one. A missing KSEC category is a
  // code fact, not a vote, and stays as the scenario drew it.
  const agreedAt = Math.max(review.agreement_threshold ?? 2, Math.floor((review.runs_requested ?? 3) / 2) + 1)
  const belowThreshold = Math.max(0, agreedAt - 1)
  for (const f of [...review.redundancies, ...review.bloom, ...review.unused_needs]) {
    if ((f.agreed_runs ?? 0) >= agreedAt) f.agreed_runs = belowThreshold
  }
  // The scenario's summary describes round 1's findings; the stored review is round 2's.
  review.summary_th = 'ชุด PLO ผ่านการตรวจ — เหลือข้อสังเกตที่เสียงยังไม่ถึงเกณฑ์'
  push(
    {
      kind: 'loop_end',
      plo_ids: [],
      need_ids: [],
      finding_reason_th: '',
      instruction_th: '',
      outcome: 'stopped',
      outcome_reason_th: 'ผ่านแล้ว — รอบที่ 2 ไม่พบข้อที่ต้องแก้เพิ่ม',
    },
    2,
    stamp(Date.parse(`${review.created_at}Z`)),
  )
  db.feedback = [...[...rows].reverse(), ...(db.feedback ?? [])]
  return rows
}

/**
 * Advance every running session whose step is due. Called lazily before each
 * request, so the Pipeline page's two-second poll is what moves a run along.
 */
export function tickSessions(): void {
  const now = Date.now()
  for (const s of getDb().sessions) {
    if (s.status !== 'running' || s.due_at === null || s.due_at > now) continue
    s.due_at = null
    s.updated_at = nowIso()
    const stage = CHECKPOINTS[s.target]
    if (s.will_fail) {
      s.will_fail = false
      s.status = 'failed'
      s.suspended_message = `mock: จำลองความล้มเหลว — ขั้น ${stage ?? 'plo_report'} เรียกโมเดลไม่สำเร็จ (หมดเวลารอผลตอบกลับ 300 วินาที)`
      continue
    }
    if (stage === undefined) {
      // Resumed past the last gate: plo_report and plo_review run, the graph
      // reaches END.
      try {
        finishSession(s.program_id)
      } catch (err) {
        s.status = 'failed'
        s.suspended_message = err instanceof Error ? err.message : String(err)
        continue
      }
      s.status = 'completed'
      continue
    }
    try {
      runStageForSession(s.program_id, stage)
    } catch (err) {
      s.status = 'failed'
      s.suspended_message = err instanceof Error ? err.message : String(err)
      continue
    }
    s.status = 'suspended'
    s.current_stage = stage
    s.suspended_message = INTERRUPT_MESSAGE[stage]
    s.target += 1
  }
}

// ----------------------------------------------------------------------------
// Background jobs (api/jobs.py)
// ----------------------------------------------------------------------------

/** JOB_KIND_LABEL_TH. */
const JOB_LABEL_TH: Record<JobKind, string> = {
  needs_pipeline: 'สกัดทักษะและรวมความต้องการ',
  skill_extraction: 'สกัดทักษะ',
  need_combination: 'รวมความต้องการ',
  plo_synthesis: 'สังเคราะห์ PLO',
  plo_review: 'ตรวจคุณภาพชุด PLO',
  plo_report: 'ออกรายงาน PLO',
  plo_revalidate: 'ตรวจ SMART ซ้ำ',
}

/** Which slots a job of each kind calls (config.py SLOTS), with a rough call
 *  count — a mock stands in for the usage rows the real LLM client writes. */
const JOB_SLOTS: Record<JobKind, Array<[string, number]>> = {
  needs_pipeline: [['extraction', 24], ['clustering', 3]],
  skill_extraction: [['extraction', 24], ['clustering', 3]],
  need_combination: [['need_combination', 8], ['need_dedup', 5]],
  plo_synthesis: [['plo_synthesis', 8], ['validation', 8]],
  plo_review: [['plo_review', 5]],
  plo_report: [],
  plo_revalidate: [['validation', 1]],
}

function addTotals(a: UsageTotals, b: UsageTotals): UsageTotals {
  return {
    calls: a.calls + b.calls,
    failed_calls: a.failed_calls + b.failed_calls,
    prompt_tokens: a.prompt_tokens + b.prompt_tokens,
    completion_tokens: a.completion_tokens + b.completion_tokens,
    reasoning_tokens: a.reasoning_tokens + b.reasoning_tokens,
    latency_ms: a.latency_ms + b.latency_ms,
  }
}

/** What a graph session calls, in pipeline order; a running one has only got through
 *  the first two. */
const SESSION_SLOTS: Array<[string, number]> = [
  ['extraction', 24],
  ['clustering', 3],
  ['need_combination', 8],
  ['need_dedup', 5],
  ['plo_synthesis', 8],
  ['validation', 8],
  ['plo_review', 5],
]

const NO_USAGE: UsageTotals = {
  calls: 0,
  failed_calls: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  reasoning_tokens: 0,
  latency_ms: 0,
}

/** The runs a seeded program with PLOs implicitly went through, oldest first,
 *  so the usage panel shows in the mock before anything has been run. */
const SEEDED_USAGE_KINDS: JobKind[] = ['skill_extraction', 'need_combination', 'plo_synthesis', 'plo_review']

interface UsageJobSource {
  job_id: string
  kind: JobKind
  started: string
  failed: boolean
}

/** GET /programs/{id}/usage, derived from the program's own jobs so a run in
 *  the mock shows up in the panel. A program that has PLOs but no mock jobs
 *  (the seeded 'complete' scenario) gets a believable history instead. Numbers
 *  are deterministic per call count. */
function mockUsage(pid: string): UsageSummary {
  let sources: UsageJobSource[] = [...of(getDb().jobs, pid)].reverse().map((job) => ({
    job_id: job.job_id,
    kind: job.kind,
    started: job.created_at,
    failed: job.status === 'failed',
  }))
  if (sources.length === 0 && of(getDb().plos, pid).length > 0) {
    const now = Date.now()
    sources = SEEDED_USAGE_KINDS.map((kind, i) => ({
      job_id: `seed-usage-${pid}-${kind}`,
      kind,
      started: new Date(now - (SEEDED_USAGE_KINDS.length - i) * 3_600_000).toISOString(),
      failed: false,
    })).reverse()
  }
  const by_job: JobUsage[] = []
  const by_session: SessionUsage[] = []
  const slotTotals = new Map<string, SlotUsage>()
  let total = NO_USAGE
  const addSlots = (by_slot: SlotUsage[]): UsageTotals => {
    const blockTotal = by_slot.reduce<UsageTotals>((acc, s) => addTotals(acc, s), NO_USAGE)
    total = addTotals(total, blockTotal)
    for (const s of by_slot) {
      const prev = slotTotals.get(s.slot)
      slotTotals.set(s.slot, prev ? { ...addTotals(prev, s), slot: s.slot } : s)
    }
    return blockTotal
  }
  // Session calls carry a session id and no job id, as in the real table.
  for (const sess of [...of(getDb().sessions, pid)].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  )) {
    const slots = sess.status === 'running' ? SESSION_SLOTS.slice(0, 2) : SESSION_SLOTS
    const by_slot: SlotUsage[] = slots.map(([slot, calls]) => ({
      slot,
      calls,
      failed_calls: sess.status === 'failed' && slot === slots[slots.length - 1][0] ? 1 : 0,
      prompt_tokens: calls * 1850,
      completion_tokens: calls * 420,
      reasoning_tokens: calls * 130,
      latency_ms: calls * 2300,
    }))
    by_session.push({
      session_id: sess.session_id,
      started: sess.created_at,
      total: addSlots(by_slot),
      by_slot,
    })
  }
  for (const job of sources) {
    const by_slot: SlotUsage[] = JOB_SLOTS[job.kind].map(([slot, calls]) => ({
      slot,
      calls,
      failed_calls: job.failed && slot === JOB_SLOTS[job.kind][0][0] ? 1 : 0,
      prompt_tokens: calls * 1850,
      completion_tokens: calls * 420,
      reasoning_tokens: calls * 130,
      latency_ms: calls * 2300,
    }))
    if (by_slot.length === 0) continue
    const jobTotal = addSlots(by_slot)
    by_job.push({
      job_id: job.job_id,
      kind: job.kind,
      label_th: JOB_LABEL_TH[job.kind] ?? '',
      started: job.started,
      total: jobTotal,
      by_slot,
    })
  }
  // The server sorts by_slot by slot name.
  const by_slot = [...slotTotals.values()].sort((a, b) => a.slot.localeCompare(b.slot))
  return { total, by_slot, by_job, by_session }
}

/** How long a job runs before it finishes. Short enough to click through, long
 *  enough that the page is seen waiting and the 2-second poll sees it end. */
function jobDuration(): number {
  return getControls().latency ? between(1500, 3000) : 300
}

/** program_busy: why this program cannot take another writer, or null. One
 *  active writer per program — a running job or a running graph session. The
 *  synchronous writers (sessions, approve, merge, copy) ask it too. */
function busyReason(pid: string): string | null {
  const db = getDb()
  const running = of(db.jobs, pid).find((j) => j.status === 'running')
  if (running) {
    return `หลักสูตรนี้มีงาน${JOB_LABEL_TH[running.kind] ?? running.kind} กำลังทำอยู่ — รอให้เสร็จก่อน`
  }
  if (of(db.sessions, pid).some((s) => s.status === 'running')) {
    return 'หลักสูตรนี้กำลังรัน pipeline อยู่ — รอให้เสร็จก่อน'
  }
  return null
}

/** why evidence cannot change, or null. The busy reason wins, then the
 *  skills-or-Needs rule (api/routes/evidence.py, evidence_lock_reason): once extraction has read the
 *  evidence, editing it would leave the rows downstream describing text that
 *  is gone, so the way to change it is an evidence-only copy. */
export function evidenceLockReason(pid: string): string | null {
  const busy = busyReason(pid)
  if (busy) return busy
  const db = getDb()
  if (of(db.skills, pid).length || of(db.needs, pid).length) {
    return 'สกัดทักษะจาก evidence แล้ว แก้ เพิ่ม หรือลบ evidence ไม่ได้ — คัดลอกหลักสูตรแบบเฉพาะข้อมูลนำเข้าหากต้องแก้'
  }
  return null
}

interface MockJob {
  pid: string
  kind: JobKind
  params: Record<string, unknown>
  /** The text the job fails with when "run ถัดไปล้มเหลว" is armed. */
  failure: string
  /** The route's old body, after its precondition checks: what the stage does
   *  and what it answered. Runs when the job finishes, not when it starts. A
   *  status of 400 or more is the job's failure, its detail the `error_th`. */
  work: () => MockResponse
  /** Started the moment this job succeeds, with no busy check: `/needs/run` is
   *  an Agent 1 job followed by an Agent 2 job, and nothing else gets between. */
  next?: MockJob
}

/** start_job: record a `running` job, answer 202 with it, and let it finish on
 *  a timer. The caller has already done every synchronous check the route does
 *  before a job exists; the one-writer rule is the last of them. */
function startJob(spec: MockJob): MockResponse {
  const busy = busyReason(spec.pid)
  if (busy) return detail(409, busy)
  return ok(launchJob(spec), 202)
}

function launchJob(spec: MockJob): JobInfo {
  // Consumed here, by the click that armed it, and spent by this job.
  const doomed = consumeFailNextRun()
  const job: JobInfo = {
    job_id: newId(),
    program_id: spec.pid,
    kind: spec.kind,
    label_th: JOB_LABEL_TH[spec.kind],
    status: 'running',
    params: spec.params,
    result: null,
    error_th: null,
    created_at: utcIso(),
    finished_at: null,
  }
  getDb().jobs.push(job)
  const work = doomed ? () => detail(500, spec.failure) : spec.work
  window.setTimeout(() => finishJob(job.job_id, work, spec.next), jobDuration())
  return job
}

/** Runs the job's work and records the outcome. Looks the job up again rather
 *  than holding the row: the panel's reset or a deleted program replaces the db
 *  under a pending timer, and a job that is gone has nothing to finish. */
function finishJob(jobId: string, work: () => MockResponse, next?: MockJob): void {
  const job = getDb().jobs.find((j) => j.job_id === jobId)
  if (!job || job.status !== 'running') return
  let outcome: MockResponse
  try {
    outcome = work()
  } catch (err) {
    outcome = detail(500, err instanceof Error ? err.message : String(err))
  }
  job.finished_at = utcIso()
  if (outcome.status < 400) {
    job.status = 'succeeded'
    // A snapshot, as the backend stores one: the result must not follow the rows
    // it describes when a later edit changes them.
    job.result = outcome.data === undefined ? null : clone(outcome.data)
    if (next) launchJob(next)
  } else {
    const reason = (outcome.data as { detail?: unknown } | undefined)?.detail
    job.status = 'failed'
    job.error_th = typeof reason === 'string' ? reason : 'งานล้มเหลว'
  }
  saveDb()
}

// ----------------------------------------------------------------------------
// The routes
// ----------------------------------------------------------------------------

/** The stage 06 review as a job. `/plos/run` chains it after synthesis, as the
 *  backend does, and `/plos/review/run` starts it alone. */
function reviewJobSpec(pid: string): MockJob {
  return {
    pid,
    kind: 'plo_review',
    params: {},
    failure: runFailureText('plo_review'),
    work: () => {
      // Built when the job finishes, from the set as it is by then, and stored
      // the way the real run replaces the previous review.
      const db = getDb()
      const degree = db.programs.find((p) => p.program_id === pid)?.degree_level ?? 'bachelor'
      const review = buildMockReview(pid, of(db.plos, pid), of(db.needs, pid), degree)
      db.reviews = [...(db.reviews ?? []).filter((x) => x.program_id !== pid), review]
      const feedback = sendBack(pid, review)
      // Send-back changed the set right after the review was stored, so the
      // review is stale by construction (the server's fingerprint would say so).
      const changed = feedback.some((f) => f.outcome === 'applied')
      return ok({ review, stale: changed, review_enabled: true, feedback })
    },
  }
}

export function buildRouter(): Router {
  const r = new Router()

  r.get('/health', () => ok({ status: 'ok' }))

  // --- programs -------------------------------------------------------------

  r.get('/programs', () => {
    const rows = [...getDb().programs]
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map((p) => ({
        program_id: p.program_id,
        name_th: p.name_th,
        name_en: p.name_en,
        field: p.field,
        faculty: p.faculty,
        degree_level: p.degree_level,
        created_at: p.created_at,
        current_stage: stageReached(p.program_id),
        session_status: latestSession(p.program_id)?.status ?? null,
        copied_from: p.copied_from ?? null,
      }))
    return ok(rows)
  })

  r.post('/programs', (req) => {
    const parsed = parseProgram(req)
    if (isResponse(parsed)) return parsed
    const db = getDb()
    const base = slugify(parsed.field)
    let candidate = base
    for (let n = 2; db.programs.some((p) => p.program_id === candidate); n++) candidate = `${base}-${n}`
    const row: ProgramRow = { ...parsed, program_id: candidate, created_at: nowIso(), copied_from: null }
    db.programs.push(row)
    return ok(row)
  })

  r.get('/programs/:pid', (req) => {
    const p = findProgram(req.params.pid)
    return p ? ok({ ...p, copied_from: p.copied_from ?? null }) : detail(404, 'Program not found')
  })

  /** GET /programs/{id}/usage — what the program's model calls cost. */
  r.get('/programs/:pid/usage', (req) =>
    findProgram(req.params.pid) ? ok(mockUsage(req.params.pid)) : detail(404, 'Program not found'),
  )

  /** POST /programs/{id}/copy — data/program_copy.py. Every evidence, skill and
   *  Need id is re-minted and every reference to one rewritten (the backend's
   *  remap_ids); plo_id is kept, since a PLO is (program_id, plo_id). Sessions
   *  are not copied, so the copy starts with no checkpoint. */
  r.post('/programs/:pid/copy', (req) => {
    const src = req.params.pid
    const db = getDb()
    const source = findProgram(src)
    if (!source) return detail(404, 'ไม่พบหลักสูตรนี้')
    // A copy taken mid-run would hold half a set: every stage deletes, then inserts.
    const busy = busyReason(src)
    if (busy) return detail(409, busy)
    // No body means a full copy, as the route reads it.
    const evidenceOnly = body<{ mode: string }>(req).mode === 'evidence_only'
    let n = 1
    while (db.programs.some((p) => p.program_id === `${src}-run-${n}`)) n++
    const newPid = `${src}-run-${n}`

    const idMap = new Map<string, string>()
    for (const e of of(db.evidence, src)) idMap.set(e.evidence_id, newId())
    for (const k of of(db.skills, src)) idMap.set(k.skill_id, newId())
    for (const nd of of(db.needs, src)) idMap.set(nd.need_id, newId())
    // Ids are uuids, so rewriting every string equal to an old id is exact.
    const remap = <T,>(row: T): T => {
      const walk = (v: unknown): unknown => {
        if (typeof v === 'string') return idMap.get(v) ?? v
        if (Array.isArray(v)) return v.map(walk)
        if (v && typeof v === 'object') {
          return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x)]))
        }
        return v
      }
      return { ...(walk(row) as T), program_id: newPid }
    }
    db.programs.push({ ...source, program_id: newPid, created_at: nowIso(), copied_from: src })
    db.evidence.push(...of(db.evidence, src).map(remap))
    // evidence_only stops at the inputs: metadata and evidence, nothing derived.
    if (!evidenceOnly) {
      db.skills.push(...of(db.skills, src).map(remap))
      db.needs.push(...of(db.needs, src).map(remap))
      db.plos.push(...of(db.plos, src).map(remap))
      // History is cloned in full mode: new row ids, new program_id on row and snapshot.
      db.superseded = [
        ...(db.superseded ?? []),
        ...of(db.superseded ?? [], src).map((row) => {
          const copy = remap(row)
          return { ...copy, id: newId(), plo: { ...copy.plo, program_id: newPid } }
        }),
      ]
      db.feedback = [
        ...(db.feedback ?? []),
        ...of(db.feedback ?? [], src).map((row) => ({ ...remap(row), id: newId() })),
      ]
    }
    return ok(findProgram(newPid))
  })

  r.put('/programs/:pid', (req) => {
    const existing = findProgram(req.params.pid)
    if (!existing) return detail(404, 'ไม่พบหลักสูตรนี้')
    const parsed = parseProgram(req)
    if (isResponse(parsed)) return parsed
    // The id never moves, even when the field it was slugged from does.
    Object.assign(existing, parsed, { program_id: existing.program_id, created_at: existing.created_at })
    return ok(existing)
  })

  r.delete('/programs/:pid', (req) => {
    const pid = req.params.pid
    const db = getDb()
    if (!findProgram(pid)) return detail(404, 'ไม่พบหลักสูตรนี้')
    const busy = busyReason(pid)
    if (busy) return detail(409, busy)
    db.programs = db.programs.filter((p) => p.program_id !== pid)
    db.evidence = db.evidence.filter((r2) => r2.program_id !== pid)
    db.skills = db.skills.filter((r2) => r2.program_id !== pid)
    db.needs = db.needs.filter((r2) => r2.program_id !== pid)
    db.plos = db.plos.filter((r2) => r2.program_id !== pid)
    db.sessions = db.sessions.filter((r2) => r2.program_id !== pid)
    db.jobs = db.jobs.filter((r2) => r2.program_id !== pid)
    db.reviews = (db.reviews ?? []).filter((r2) => r2.program_id !== pid)
    db.superseded = (db.superseded ?? []).filter((r2) => r2.program_id !== pid)
    db.feedback = (db.feedback ?? []).filter((r2) => r2.program_id !== pid)
    return { status: 204 }
  })

  // --- evidence -------------------------------------------------------------

  r.get('/programs/:pid/evidence', (req) => ok(of(getDb().evidence, req.params.pid)))

  r.get('/programs/:pid/evidence/lock', (req) => {
    const reason = evidenceLockReason(req.params.pid)
    return ok({ locked: reason !== null, reason_th: reason })
  })

  r.put('/programs/:pid/evidence/:eid', (req) => {
    const { pid, eid } = req.params
    const locked = evidenceLockReason(pid)
    if (locked) return detail(409, locked)
    const row = of(getDb().evidence, pid).find((e) => e.evidence_id === eid)
    if (!row) return detail(404, 'ไม่พบหลักฐานนี้')
    const b = body<EvidenceRow>(req)
    if (!STAKEHOLDER_TYPES.includes(b.stakeholder_type as (typeof STAKEHOLDER_TYPES)[number])) {
      return invalid([{ loc: ['body', 'stakeholder_type'], msg: 'Input should be a valid StakeholderType', type: 'enum' }])
    }
    Object.assign(row, {
      stakeholder_type: b.stakeholder_type as string,
      source_name: b.source_name ?? row.source_name,
      raw_text_th: b.raw_text_th ?? row.raw_text_th,
      source_url: b.source_url ?? null,
      classification: classifyEvidence(b.stakeholder_type as string),
    })
    return ok(row)
  })

  r.post('/programs/:pid/evidence', (req) => {
    const locked = evidenceLockReason(req.params.pid)
    if (locked) return detail(409, locked)
    const b = body<EvidenceRow>(req)
    const errors: { loc: string[]; msg: string; type: string }[] = []
    for (const key of ['evidence_id', 'program_id', 'source_name', 'raw_text_th'] as const) {
      if (typeof b[key] !== 'string') errors.push({ loc: ['body', key], msg: 'Field required', type: 'missing' })
    }
    if (!STAKEHOLDER_TYPES.includes(b.stakeholder_type as (typeof STAKEHOLDER_TYPES)[number])) {
      errors.push({ loc: ['body', 'stakeholder_type'], msg: 'Input should be a valid StakeholderType', type: 'enum' })
    }
    if (errors.length) return invalid(errors)
    // Stored under the body's program_id, as the route does; classification is
    // the route's output, never its input.
    const row: EvidenceRow = {
      evidence_id: b.evidence_id as string,
      program_id: b.program_id as string,
      stakeholder_type: b.stakeholder_type as string,
      source_name: b.source_name as string,
      source_url: b.source_url ?? null,
      raw_text_th: b.raw_text_th as string,
      raw_text_en: b.raw_text_en ?? null,
      collected_at: b.collected_at ?? nowIso(),
      classification: classifyEvidence(b.stakeholder_type as string),
      classification_rationale_th: b.classification_rationale_th ?? null,
      metadata: b.metadata ?? {},
    }
    const db = getDb()
    db.evidence = [...db.evidence.filter((e) => e.evidence_id !== row.evidence_id), row]
    return ok(row)
  })

  r.delete('/programs/:pid/evidence/:eid', (req) => {
    const { pid, eid } = req.params
    const locked = evidenceLockReason(pid)
    if (locked) return detail(409, locked)
    const db = getDb()
    // SkillTable.source_evidence_id is a foreign key into the evidence table.
    if (db.skills.some((s) => s.source_evidence_id === eid)) {
      return detail(409, 'ลบไม่ได้ — หลักฐานนี้ถูกใช้ในการสกัดทักษะแล้ว')
    }
    const before = db.evidence.length
    db.evidence = db.evidence.filter((e) => !(e.program_id === pid && e.evidence_id === eid))
    return db.evidence.length < before ? { status: 204 } : detail(404, 'ไม่พบหลักฐานนี้')
  })

  // --- needs ----------------------------------------------------------------

  r.get('/programs/:pid/needs', (req) => {
    const rows = sortNeeds(of(getDb().needs, req.params.pid))
    return ok(req.query.get('active_only') === 'true' ? activeNeeds(rows) : rows)
  })

  r.get('/programs/:pid/needs/skill-groups', (req) =>
    ok(skillGroupsOf(req.params.pid, of(getDb().skills, req.params.pid))),
  )

  /** NeedRepository.split, refused in the real route's order: 409 busy
   *  (sync_writer), 404, 422 excluded, 422 not merged, 409 for a PLO. */
  r.post('/programs/:pid/needs/:nid/split', (req) => {
    const { pid, nid } = req.params
    const db = getDb()
    const busy = busyReason(pid)
    if (busy) return detail(409, busy)
    const need = of(db.needs, pid).find((n) => n.need_id === nid)
    if (!need) return detail(404, 'ไม่พบ Need นี้')
    if (need.excluded_at !== null) return detail(422, 'คืน Need ก่อนแยก')
    if (need.merged_from.length === 0) return detail(422, 'Need นี้ไม่ได้มาจากการรวม จึงแยกไม่ได้')
    if (of(db.plos, pid).some((p) => p.source_need_ids.includes(nid))) {
      return detail(409, 'Need นี้ถูกใช้สร้าง PLO แล้ว — แยกก่อนสร้าง PLO หรือรันสังเคราะห์ PLO ใหม่หลังแยก')
    }
    const originals = of(db.needs, pid).filter((n) => need.merged_from.includes(n.need_id))
    for (const o of originals) o.merged_into = null
    db.needs = db.needs.filter((n) => n.need_id !== nid)
    return ok(sortNeeds(originals))
  })

  /** The designer's merge, refused in the route's order: 409 busy
   *  (sync_writer), 422 on the request's shape and the rows, 409 for a PLO,
   *  422 for the core floor. The sentence is faked: the real route asks the
   *  model for it and answers 502 when it fails. */
  r.post('/programs/:pid/needs/merge', (req) => {
    const { pid } = req.params
    const db = getDb()
    const busy = busyReason(pid)
    if (busy) return detail(409, busy)
    const body = (req.body ?? {}) as { need_ids?: string[]; reason_th?: string | null }
    const ids = body.need_ids ?? []
    if (new Set(ids).size !== ids.length) return detail(422, 'เลือก Need ซ้ำ')
    if (ids.length < 2 || ids.length > 5) return detail(422, 'เลือก Need 2-5 ข้อเพื่อรวม')
    const missing = ids.filter((id) => !of(db.needs, pid).some((n) => n.need_id === id))
    if (missing.length) return detail(422, `ไม่พบ Need: ${missing.join(', ')}`)
    const picked = ids.map((id) => of(db.needs, pid).find((n) => n.need_id === id)) as NeedRow[]
    const inactive = picked.find((n) => n.merged_into !== null || n.excluded_at !== null)
    if (inactive) return detail(422, `Need ${inactive.need_id} ไม่อยู่ในชุดที่ใช้งาน`)
    const unwritten = picked.filter((n) => fallbackKind(n.statement_th))
    if (unwritten.length) {
      return detail(
        422,
        'ยังไม่ได้เขียนประโยคสำหรับ Need: ' +
          `${unwritten.map((n) => n.need_id).join(', ')} — ผู้ออกแบบหลักสูตรต้องเขียนประโยคเอง ` +
          'หรือรันขั้นรวมทักษะเป็น Need ใหม่ ก่อนนำมารวม',
      )
    }
    const cited = ids.filter((id) => of(db.plos, pid).some((p) => p.source_need_ids.includes(id)))
    if (cited.length) {
      return detail(409, `มี PLO อ้างถึง Need: ${cited.join(', ')} — ลบหรือรวม PLO ก่อนรวม Need`)
    }
    // Worst case: the merged Need counts as core whenever any member is.
    const active = activeNeeds(of(db.needs, pid))
    // Mirrors is_core_candidate: not optional, in scope, written.
    const isCoreCandidate = (n: NeedRow) =>
      !n.is_optional && scopeVerdict(n) === 'in_scope' && !fallbackKind(n.statement_th)
    const currentCore = active.filter(isCoreCandidate).length
    const selectedCore = picked.filter(isCoreCandidate).length
    const projected = currentCore - selectedCore + (selectedCore > 0 ? 1 : 0)
    if (projected < MIN_CORE_AFTER_MERGE && projected < currentCore) {
      return detail(
        422,
        `การรวมนี้จะเหลือ Need หลัก ${projected} ข้อ ต่ำกว่าขั้นต่ำ ${MIN_CORE_AFTER_MERGE} ข้อ`,
      )
    }
    const merged: NeedRow = {
      ...picked[0],
      need_id: newId(),
      statement_th: `(จำลอง) ${picked.map((n) => n.statement_th).join(' และ ')}`,
      ksec_categories: [...new Set(picked.flatMap((n) => n.ksec_categories))].sort(),
      member_skill_ids: [...new Set(picked.flatMap((n) => n.member_skill_ids))],
      top_skill_ids: picked.flatMap((n) => n.top_skill_ids.slice(0, 2)).slice(0, 7),
      source_evidence_ids: [...new Set(picked.flatMap((n) => n.source_evidence_ids))],
      source_stakeholder_types: [...new Set(picked.flatMap((n) => n.source_stakeholder_types))],
      freq: picked.reduce((a, n) => a + n.freq, 0),
      demand_score: Math.max(...picked.map((n) => n.demand_score)),
      is_optional: picked.every((n) => n.is_optional),
      in_field_skill_count: picked.reduce((a, n) => a + n.in_field_skill_count, 0),
      graduate_capability_skill_count: picked.reduce((a, n) => a + n.graduate_capability_skill_count, 0),
      merged_from: ids,
      merged_into: null,
      merged_by: 'designer',
      excluded_at: null,
      merge_reason_th: body.reason_th?.trim() || 'ผู้ออกแบบหลักสูตรเลือกรวม Need เหล่านี้',
    }
    for (const n of picked) n.merged_into = merged.need_id
    db.needs.push(merged)
    return ok(merged)
  })

  /** NeedRepository.set_excluded, refused in the real route's order: 409 busy
   *  (sync_writer), 404, 422 for a row that is not active, 409 for a PLO. */
  r.post('/programs/:pid/needs/:nid/exclude', (req) => {
    const { pid, nid } = req.params
    const db = getDb()
    const busy = busyReason(pid)
    if (busy) return detail(409, busy)
    const need = of(db.needs, pid).find((n) => n.need_id === nid)
    if (!need) return detail(404, 'ไม่พบ Need นี้')
    if (need.merged_into !== null) {
      return detail(422, 'Need นี้ถูกรวมเข้ากับ Need อื่นแล้ว — ตัด Need ที่รวมแล้วแทน')
    }
    if (need.excluded_at !== null) return detail(422, 'Need นี้ถูกตัดออกอยู่แล้ว')
    if (of(db.plos, pid).some((p) => p.source_need_ids.includes(nid))) {
      return detail(409, 'มี PLO อ้างถึง Need นี้ — ลบหรือรวม PLO ก่อนตัด Need')
    }
    need.excluded_at = new Date().toISOString()
    return ok(need)
  })

  r.post('/programs/:pid/needs/:nid/restore', (req) => {
    const { pid, nid } = req.params
    const busy = busyReason(pid)
    if (busy) return detail(409, busy)
    const need = of(getDb().needs, pid).find((n) => n.need_id === nid)
    if (!need) return detail(404, 'ไม่พบ Need นี้')
    if (need.merged_into !== null) {
      return detail(422, 'Need นี้ถูกรวมเข้ากับ Need อื่นแล้ว — ตัด Need ที่รวมแล้วแทน')
    }
    if (need.excluded_at === null) return detail(422, 'Need นี้ไม่ได้ถูกตัดออก')
    need.excluded_at = null
    return ok(need)
  })

  r.get('/programs/:pid/needs/skills', (req) => ok(of(getDb().skills, req.params.pid)))

  r.get('/programs/:pid/needs/:nid/trace', (req) => {
    const db = getDb()
    const need = of(db.needs, req.params.pid).find((n) => n.need_id === req.params.nid)
    if (!need) return detail(404, 'Need not found')
    const evidenceIds = new Set(need.source_evidence_ids)
    return ok({
      need,
      skills: db.skills.filter((s) => need.member_skill_ids.includes(s.skill_id)),
      evidence: of(db.evidence, req.params.pid).filter((e) => evidenceIds.has(e.evidence_id)),
    })
  })

  /** _build_stage_state: program, then evidence. */
  const extractionPrecondition = (pid: string): MockResponse | null => {
    if (!findProgram(pid)) return detail(404, 'Program not found')
    if (!of(getDb().evidence, pid).length) {
      return detail(422, 'ไม่มี evidence สำหรับโปรแกรมนี้ กรุณาเพิ่ม evidence ก่อน')
    }
    return null
  }

  // The stage runs below answer 202 with a job, and what they used to answer is
  // the job's `result`, written when it finishes. Each does its synchronous
  // checks (404/422) first, as the real routes do before any job row exists.

  r.post('/programs/:pid/needs/run', (req) => {
    const pid = req.params.pid
    const refused = extractionPrecondition(pid)
    if (refused) return refused
    return startJob({
      pid,
      kind: 'skill_extraction',
      params: { note_th: body<{ note_th: string }>(req).note_th ?? null },
      failure: runFailureText('skill_extraction'),
      work: () => {
        const { skills, dropped } = extractSkills(pid, of(getDb().evidence, pid))
        replaceRows('skills', pid, skills)
        return ok({ skills, dropped_ungrounded_count: dropped })
      },
      next: {
        pid,
        kind: 'need_combination',
        params: { note_th: body<{ note_th: string }>(req).note_th ?? null },
        failure: runFailureText('need_combination'),
        work: () => {
          const needs = combineNeeds(pid, of(getDb().skills, pid))
          replaceRows('needs', pid, needs)
          return ok({ needs, dropped_ungrounded_count: 0 })
        },
      },
    })
  })

  r.post('/programs/:pid/needs/skills/run', (req) => {
    const pid = req.params.pid
    const refused = extractionPrecondition(pid)
    if (refused) return refused
    return startJob({
      pid,
      kind: 'skill_extraction',
      params: { note_th: body<{ note_th: string }>(req).note_th ?? null },
      failure: runFailureText('skill_extraction'),
      work: () => {
        // Needs are left as they were, pointing at skill ids this run replaced.
        const { skills, dropped } = extractSkills(pid, of(getDb().evidence, pid))
        replaceRows('skills', pid, skills)
        return ok({ skills, dropped_ungrounded_count: dropped })
      },
    })
  })

  r.post('/programs/:pid/needs/combine/run', (req) => {
    const pid = req.params.pid
    if (!findProgram(pid)) return detail(404, 'Program not found')
    if (!of(getDb().skills, pid).length) {
      return detail(422, 'ยังไม่มีทักษะที่สกัดไว้ กรุณารัน Skill Extraction ก่อน')
    }
    return startJob({
      pid,
      kind: 'need_combination',
      params: { note_th: body<{ note_th: string }>(req).note_th ?? null },
      failure: runFailureText('need_combination'),
      work: () => {
        const needs = combineNeeds(pid, of(getDb().skills, pid))
        replaceRows('needs', pid, needs)
        return ok({ needs, dropped_ungrounded_count: 0 })
      },
    })
  })

  // --- plos -----------------------------------------------------------------

  r.get('/programs/:pid/plos', (req) => ok(sortPlos(of(getDb().plos, req.params.pid))))

  // Newest first, ties by plo_id, as the server orders them.
  r.get('/programs/:pid/plos/superseded', (req) => {
    if (!findProgram(req.params.pid)) return detail(404, 'Program not found')
    const rows = of(getDb().superseded ?? [], req.params.pid)
    return ok(
      [...rows].sort(
        (a, b) => b.superseded_at.localeCompare(a.superseded_at) || a.plo.plo_id.localeCompare(b.plo.plo_id),
      ),
    )
  })

  // Newest first, as the server orders them.
  r.get('/programs/:pid/plos/feedback', (req) => {
    if (!findProgram(req.params.pid)) return detail(404, 'Program not found')
    return ok(
      [...of(getDb().feedback ?? [], req.params.pid)].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    )
  })

  r.get('/programs/:pid/plos/export/matrix.xlsx', (req) => {
    const pid = req.params.pid
    const plos = sortPlos(of(getDb().plos, pid))
    if (!plos.length) {
      return detail(422, 'ยังไม่มี PLO สำหรับโปรแกรมนี้ กรุณารัน PLO Synthesis ก่อน')
    }
    const needs = new Map(of(getDb().needs, pid).map((n) => [n.need_id, n]))
    const rows = [
      ['PLO', 'ข้อความ', 'Bloom', 'KSEC', 'ประเภท', 'SMART'],
      ...plos.map((p) => [
        p.plo_id,
        p.statement_th,
        p.bloom_level,
        [...new Set(p.source_need_ids.flatMap((id) => needs.get(id)?.ksec_categories ?? ['?']))].join(', '),
        p.is_optional ? 'เสริม' : 'หลัก',
        p.smart_escalated ? 'ต้องแก้ด้วยมือ' : 'ผ่าน',
      ]),
    ]
    return { status: 200, data: buildXlsx('PLO (mock)', rows), contentType: XLSX_TYPE }
  })

  r.get('/programs/:pid/plos/:ploId/trace', (req) => {
    const db = getDb()
    const pid = req.params.pid
    const plo = of(db.plos, pid).find((p) => p.plo_id === req.params.ploId)
    if (!plo) return detail(404, 'PLO not found')
    const needIds = new Set(plo.source_need_ids)
    const evidenceIds = new Set(plo.source_evidence_ids)
    const clusters = of(db.needs, pid).filter((n) => needIds.has(n.need_id))
    const evidence = of(db.evidence, pid).filter((e) => evidenceIds.has(e.evidence_id))
    return ok({
      plo,
      clusters,
      evidence,
      missing_need_ids: [...needIds].filter((id) => !clusters.some((n) => n.need_id === id)).sort(),
      missing_evidence_ids: [...evidenceIds].filter((id) => !evidence.some((e) => e.evidence_id === id)).sort(),
    })
  })

  r.get('/programs/:pid/plos/validation', (req) => {
    if (!findProgram(req.params.pid)) return detail(404, 'Program not found')
    const enabled = getControls().validationEnabled
    return ok({ enabled, model: enabled ? 'z-ai/glm-5.3-flash' : '' })
  })

  r.post('/programs/:pid/plos/run', (req) => {
    const pid = req.params.pid
    if (!findProgram(pid)) return detail(404, 'Program not found')
    if (!of(getDb().needs, pid).length) {
      return detail(422, 'ไม่มี Needs สำหรับโปรแกรมนี้ กรุณารัน Need Combination ก่อน')
    }
    const { note_th, run_validation } = body<{ note_th: string; run_validation: boolean }>(req)
    return startJob({
      pid,
      kind: 'plo_synthesis',
      params: { note_th: note_th ?? null, run_validation: run_validation ?? true },
      failure: runFailureText('plo_synthesis'),
      // The backend chains the review once synthesis succeeds.
      next: reviewJobSpec(pid),
      work: () => {
        const plos = synthesizePlos(pid, of(getDb().needs, pid), of(getDb().skills, pid))
        // The system switch wins over the request, as smart_agent orders them:
        // DISABLED is checked before SKIPPED, and both only skip the agent —
        // the pure-code verdict synthesizePlos already holds stays.
        const skip = !getControls().validationEnabled
          ? 'ไม่ได้ตรวจ (ปิดการใช้ validation agent)'
          : run_validation === false
            ? 'ไม่ได้ตรวจ (ปิดการตรวจในรอบนี้)'
            : null
        if (skip) {
          for (const plo of plos) {
            // code_only_result: no soft verdict is manufactured, so a criterion
            // fails only where a hard finding (S_verb, M_forbidden…) says so.
            const hard = plo.smart_check.findings.filter((f) => f.severity === 'hard')
            const failed = (letter: string) => hard.some((f) => f.criterion.startsWith(letter))
            plo.smart_validated_by = 'code_only'
            plo.smart_diagnosis_th = skip
            plo.soft_flags = []
            plo.smart_check = {
              ...plo.smart_check,
              specific: !failed('S'),
              measurable: !failed('M'),
              achievable: true,
              relevant: !failed('R'),
              timely: true,
              findings: hard,
            }
          }
        }
        replaceRows('plos', pid, plos)
        // A re-synthesis starts the set over, as the server's delete_by_program does.
        getDb().superseded = (getDb().superseded ?? []).filter((x) => x.program_id !== pid)
        getDb().feedback = (getDb().feedback ?? []).filter((x) => x.program_id !== pid)
        return ok(plos)
      },
    })
  })

  r.post('/programs/:pid/plos/report/run', (req) => {
    const pid = req.params.pid
    if (!of(getDb().plos, pid).length) {
      return detail(422, 'ยังไม่มี PLO สำหรับโปรแกรมนี้ กรุณารัน PLO Synthesis ก่อน')
    }
    return startJob({
      pid,
      kind: 'plo_report',
      params: {},
      failure: runFailureText('plo_report'),
      work: () => {
        // Built when the job finishes and stored: this is the designer's approval.
        return ok(storeReport(pid))
      },
    })
  })

  /** The stored report; stale when the set changed after it was stored. The
   *  mock compares the PLO rows themselves, since nothing here fingerprints. */
  r.get('/programs/:pid/plos/report', (req) => {
    const pid = req.params.pid
    if (!findProgram(pid)) return detail(404, 'Program not found')
    const row = (getDb().reports ?? []).find((x) => x.program_id === pid)
    if (!row) return ok({ report: null, stale: false, created_at: null })
    const stored = (row.report as { plos: PloRow[] }).plos
    const stale = JSON.stringify(stored) !== JSON.stringify(sortPlos(of(getDb().plos, pid)))
    return ok({ report: row.report, stale, created_at: row.created_at })
  })

  /** The stage 06 set review: what is stored, if anything. The mock never
   *  reports it stale — nothing here fingerprints the set. */
  r.get('/programs/:pid/plos/review', (req) => {
    const review = (getDb().reviews ?? []).find((x) => x.program_id === req.params.pid) ?? null
    return ok({ review, stale: false, review_enabled: true })
  })

  r.post('/programs/:pid/plos/review/run', (req) => {
    const pid = req.params.pid
    if (!of(getDb().plos, pid).length) {
      return detail(422, 'ยังไม่มี PLO สำหรับโปรแกรมนี้ กรุณารัน PLO Synthesis ก่อน')
    }
    return startJob(reviewJobSpec(pid))
  })

  r.post(
    '/programs/:pid/plos/from-needs',
    (req) => {
      const pid = req.params.pid
      const b = body<{ need_ids: string[]; note_th: string | null }>(req)
      const needIds = Array.isArray(b.need_ids) ? b.need_ids.map(String) : []
      // Checked before anything else, as the server does.
      if (needIds.length > MAX_MERGE_NEEDS) return detail(422, 'เลือก Need 2-5 ข้อเพื่อรวมเป็น PLO')
      if (needIds.length < 2) {
        return invalid([{ loc: ['body', 'need_ids'], msg: 'List should have at least 2 items after validation, not ' + needIds.length, type: 'too_short' }])
      }
      if (!findProgram(pid)) return detail(404, 'ไม่พบหลักสูตรนี้')
      const busy = busyReason(pid)
      if (busy) return detail(409, busy)
      const db = getDb()
      const allNeeds = of(db.needs, pid)
      const byId = new Map(allNeeds.map((n) => [n.need_id, n]))
      const missing = needIds.filter((id) => !byId.has(id))
      if (missing.length) return detail(422, `ไม่พบ Need: ${missing.join(', ')}`)

      const selected = needIds.map((id) => byId.get(id) as NeedRow)
      const isOptional = selected.every((n) => n.is_optional)
      const existing = of(db.plos, pid)
      const superseded = existing.filter((p) => p.source_need_ids.some((id) => needIds.includes(id)))
      const supersededIds = new Set(superseded.map((p) => p.plo_id))
      const surviving = existing.filter((p) => !supersededIds.has(p.plo_id))
      const currentCore = existing.filter((p) => !p.is_optional).length
      const projectedCore = surviving.filter((p) => !p.is_optional).length + (isOptional ? 0 : 1)

      if (projectedCore > MAX_CORE_PLOS) {
        return detail(
          422,
          `การรวมนี้จะทำให้มี PLO หลัก ${projectedCore} ข้อ เกินเพดาน ${MAX_CORE_PLOS} ข้อ เลือก Need ที่มี PLO อยู่แล้วเข้ามารวมด้วย เพื่อให้การรวมนี้แทนที่ PLO เดิมแทนที่จะเพิ่มข้อใหม่`,
        )
      }
      if (projectedCore < MIN_CORE_AFTER_MERGE && projectedCore < currentCore) {
        return detail(
          422,
          `การรวมนี้จะเหลือ PLO หลัก ${projectedCore} ข้อ ต่ำกว่าขั้นต่ำของการรวม ${MIN_CORE_AFTER_MERGE} ข้อ รวม Need ที่ยังไม่มี PLO ขึ้นมาเป็นข้อใหม่ก่อน แล้วจึงรวมข้อที่ซ้ำซ้อนกัน`,
        )
      }
      if (consumeFailNextRun()) return detail(502, 'สร้าง PLO ไม่สำเร็จ กรุณาลองใหม่')

      const plo = replaceFromNeeds(pid, selected, 'designer')
      return ok(plo)
    },
    'slow',
  )

  r.put('/programs/:pid/plos/:ploId', (req) => {
    const pid = req.params.pid
    const b = body<PloRow>(req)
    const errors: { loc: string[]; msg: string; type: string }[] = []
    for (const key of ['statement_th', 'action_verb_th', 'rationale_th'] as const) {
      if (typeof b[key] !== 'string') errors.push({ loc: ['body', key], msg: 'Field required', type: 'missing' })
    }
    if (!BLOOM_LEVELS.includes(String(b.bloom_level))) {
      errors.push({ loc: ['body', 'bloom_level'], msg: 'Input should be a valid BloomLevel', type: 'enum' })
    }
    if (errors.length) return invalid(errors)

    const db = getDb()
    const match = of(db.plos, pid).find((p) => p.plo_id === req.params.ploId)
    if (!match) return detail(404, 'PLO not found')

    // PLOStatementUpdate: text only. Verdict fields in the body are ignored.
    const text = {
      statement_th: b.statement_th as string,
      statement_en: b.statement_en ?? null,
      bloom_level: b.bloom_level as string,
      action_verb_th: b.action_verb_th as string,
      rationale_th: b.rationale_th as string,
      distinctive_feature_th: b.distinctive_feature_th ?? null,
    }
    const edited = text.statement_th.trim() !== match.statement_th.trim()
    if (!edited) {
      Object.assign(match, text, { version: match.version + 1 })
      return ok(match)
    }
    const known = new Set(of(db.needs, pid).map((n) => n.need_id))
    const fails = hardFailures(text.statement_th, text.action_verb_th, match.source_need_ids, known)
    Object.assign(match, text, {
      version: match.version + 1,
      smart_check: codeVerdict(fails),
      soft_flags: [],
      smart_escalated: fails.length > 0,
      smart_validated_by: 'stale',
      smart_diagnosis_th:
        'แก้ข้อความแล้ว ตรวจด้วยกฎพื้นฐานเท่านั้น — กด "ตรวจ SMART ซ้ำ" เพื่อให้ผู้ตรวจอ่านประโยคใหม่',
    } satisfies Partial<PloRow>)
    return ok(match)
  })

  r.post('/programs/:pid/plos/:ploId/revalidate', (req) => {
    const { pid, ploId } = req.params
    if (!findProgram(pid)) return detail(404, 'Program not found')
    const db = getDb()
    const found = of(db.plos, pid).find((p) => p.plo_id === ploId)
    if (!found) return detail(404, 'PLO not found')
    const cited = of(db.needs, pid).filter((n) => found.source_need_ids.includes(n.need_id))
    if (!cited.length) {
      return detail(422, `${found.plo_id} อ้างถึง Need ที่ไม่มีอยู่แล้ว — ตรวจร่องรอยหลักฐานก่อน`)
    }
    return startJob({
      pid,
      kind: 'plo_revalidate',
      params: { plo_id: ploId },
      failure: 'ตรวจ SMART ไม่สำเร็จ กรุณาลองใหม่',
      work: () => {
        // Read again when the job finishes: the PLO may have been edited, or
        // the set re-synthesised, while it ran.
        const now = getDb()
        const match = of(now.plos, pid).find((p) => p.plo_id === ploId)
        if (!match) return detail(404, 'PLO not found')
        const allNeeds = of(now.needs, pid)

        // Simplification: the agent's repairs are not simulated. A statement that
        // still fails the code gate escalates after three spent repairs; one that
        // passes it gets a clean agent verdict.
        const statement = stripOutcomePrefix(match.statement_th)
        const fails = hardFailures(statement, match.action_verb_th, match.source_need_ids, new Set(allNeeds.map((n) => n.need_id)))
        const verdict: Partial<PloRow> = fails.length
          ? {
              smart_check: codeVerdict(fails),
              soft_flags: [],
              smart_escalated: true,
              smart_retry_count: 3,
              smart_validated_by: 'agent',
              smart_diagnosis_th:
                'ผู้ตรวจขอให้แก้สามรอบแล้วแต่ประโยคยังไม่ผ่านเกณฑ์บังคับ ต้องเขียนใหม่ด้วยมือตามข้อที่ไม่ผ่านด้านล่าง',
            }
          : {
              smart_check: passingCheck(),
              soft_flags: [],
              smart_escalated: false,
              smart_retry_count: 0,
              smart_validated_by: 'agent',
              smart_diagnosis_th: null,
            }
        Object.assign(match, { statement_th: statement, version: match.version + 1 }, verdict)
        return ok(match)
      },
    })
  })

  // --- jobs -----------------------------------------------------------------

  /** GET /programs/{id}/jobs — newest first, the latest 20; `active=true` keeps
   *  only the running ones. The db holds them oldest first, so reverse a copy. */
  r.get('/programs/:pid/jobs', (req) => {
    const activeOnly = req.query.get('active') === 'true'
    const rows = of(getDb().jobs, req.params.pid)
      .filter((j) => !activeOnly || j.status === 'running')
      .reverse()
      .slice(0, 20)
    return ok(rows)
  })

  r.get('/programs/:pid/jobs/:jid', (req) => {
    const job = of(getDb().jobs, req.params.pid).find((j) => j.job_id === req.params.jid)
    return job ? ok(job) : detail(404, 'ไม่พบงานนี้')
  })

  // --- sessions -------------------------------------------------------------

  r.get('/programs/:pid/sessions', (req) =>
    ok(
      of(getDb().sessions, req.params.pid)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .map(publicSession),
    ),
  )

  r.post('/programs/:pid/sessions', (req) => {
    const pid = req.params.pid
    if (!findProgram(pid)) return detail(404, 'Program not found')
    if (!of(getDb().evidence, pid).length) {
      return detail(
        422,
        'ยังไม่มี evidence สำหรับหลักสูตรนี้ — เพิ่มหลักฐานที่ขั้น Stakeholder Needs ก่อนเริ่มรัน',
      )
    }
    const busy = busyReason(pid)
    if (busy) return detail(409, busy)
    const sessionId = newId()
    const now = nowIso()
    const row: SessionRow = {
      session_id: sessionId,
      program_id: pid,
      thread_id: `${pid}:${sessionId}`,
      status: 'running',
      current_stage: null,
      suspended_message: null,
      created_at: now,
      updated_at: now,
      due_at: Date.now() + stepDuration(),
      target: 0,
      will_fail: consumeFailNextRun(),
    }
    getDb().sessions.push(row)
    return ok(publicSession(row))
  })

  const findSession = (pid: string, sid: string): SessionRow | undefined =>
    getDb().sessions.find((s) => s.session_id === sid && s.program_id === pid)

  r.get('/programs/:pid/sessions/:sid', (req) => {
    const s = findSession(req.params.pid, req.params.sid)
    return s ? ok(publicSession(s)) : detail(404, 'Session not found')
  })

  r.post('/programs/:pid/sessions/:sid/approve', (req) => {
    const s = findSession(req.params.pid, req.params.sid)
    if (!s) return detail(404, 'Session not found')
    if (s.status !== 'suspended') return detail(409, `Session is '${s.status}', not suspended`)
    // The suspended session itself does not count as running; a job does.
    const busy = busyReason(req.params.pid)
    if (busy) return detail(409, busy)
    // set_status keeps current_stage and the message: a resumed run still names
    // the gate it came from until it reaches the next one.
    s.status = 'running'
    s.updated_at = nowIso()
    s.due_at = Date.now() + stepDuration()
    s.will_fail = consumeFailNextRun()
    return ok(publicSession(s))
  })

  r.post('/programs/:pid/sessions/:sid/reject', (req) => {
    const s = findSession(req.params.pid, req.params.sid)
    if (!s) return detail(404, 'Session not found')
    if (s.status !== 'suspended') return detail(409, `Session is '${s.status}', not suspended`)
    s.status = 'rejected'
    s.updated_at = nowIso()
    return ok(publicSession(s))
  })

  r.delete('/programs/:pid/sessions/:sid', (req) => {
    const s = findSession(req.params.pid, req.params.sid)
    if (!s) return detail(404, 'ไม่พบ session นี้')
    if (s.status === 'running') {
      return detail(409, 'session นี้กำลังทำงานอยู่ — รอให้จบหรือกด reject ที่ checkpoint ก่อนลบ')
    }
    const db = getDb()
    db.sessions = db.sessions.filter((x) => x !== s)
    return { status: 204 }
  })

  return r
}

// ----------------------------------------------------------------------------
// classify-stream (served through fetch, not axios)
// ----------------------------------------------------------------------------

/**
 * The SSE events GET /evidence/classify-stream emits, in order, with the
 * classification applied to the stored rows as each item is reached. Every
 * item is reclassified, not only the unclassified ones — as the route does.
 */
export function classifyStream(pid: string): { events: object[]; apply: (index: number) => void } {
  const items = of(getDb().evidence, pid)
  const total = items.length
  const events: object[] = [{ status: 'started', total }]
  items.forEach((e, i) => {
    events.push({
      status: 'progress',
      index: i + 1,
      total,
      evidence_id: e.evidence_id,
      source_name: e.source_name,
      classification: classifyEvidence(e.stakeholder_type),
    })
  })
  events.push({ status: 'done', total })
  return {
    events,
    apply: (index: number) => {
      const item = items[index]
      if (item) item.classification = classifyEvidence(item.stakeholder_type)
    },
  }
}

