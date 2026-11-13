/**
 * The mock backend's state: one in-memory database, persisted to
 * sessionStorage so a reload (Pipeline navigates with `window.location`) keeps
 * what the designer has clicked through. Closing the tab, or "รีเซ็ต" in the
 * panel, is what clears it.
 *
 * The row types mirror the Pydantic models in src/curriculum_agent/models.py —
 * the wire shape, not the frontend's narrower interfaces — so a page that starts
 * reading another field finds it here the way it would on the real API.
 */
import type { JobInfo } from '../api/jobs'
import type { PLO, SupersededPLO } from '../types/plo'
import type { FeedbackAction, PLOSetReview } from '../types/ploReview'

export type ScenarioName = 'empty' | 'checkpoint' | 'complete' | 'many'

export const SCENARIOS: { name: ScenarioName; label: string }[] = [
  { name: 'empty', label: 'ว่าง — ยังไม่มีหลักสูตร' },
  { name: 'checkpoint', label: 'รอตรวจ Need (checkpoint)' },
  { name: 'complete', label: 'ครบทุกขั้น — PLO ทุกสถานะ' },
  { name: 'many', label: 'หลายหลักสูตร หลายสถานะ' },
]

export function isScenarioName(value: string | null): value is ScenarioName {
  return SCENARIOS.some((s) => s.name === value)
}

/** ProgramMetadata. */
export interface ProgramRow {
  program_id: string
  name_th: string
  name_en: string
  field: string
  isced_code: string | null
  degree_level: 'bachelor' | 'master' | 'doctoral'
  duration_years: number
  faculty: string
  university: string
  scope_th: string
  professional_council: string | null
  accreditation_body: string | null
  subject_benchmark_ref: string | null
  program_objectives_th: string[]
  program_goals_th: string[]
  created_at: string
  /** Set only by POST /programs/{id}/copy. Optional here because the seeded
   *  scenarios predate the field; every read treats a missing value as null. */
  copied_from?: string | null
}

/** StakeholderEvidence. `unclassified` is a pre-migration value the current
 *  model rejects on read — the mock only seeds it into one program in the
 *  `many` scenario, so the page's "จำแนกหลักฐาน" button has something to do. */
export interface EvidenceRow {
  evidence_id: string
  program_id: string
  stakeholder_type: string
  source_name: string
  source_url: string | null
  raw_text_th: string
  raw_text_en: string | null
  collected_at: string
  classification: 'requirement' | 'general' | 'unclassified'
  classification_rationale_th: string | null
  metadata: Record<string, unknown>
}

/** ExtractedSkill. */
export interface SkillRow {
  skill_id: string
  program_id: string
  skill_name_th: string
  skill_name_en: string | null
  ksec_category: 'K' | 'S' | 'E' | 'C'
  bloom_level: string
  evidence_span_th: string
  source_evidence_id: string
  source_stakeholder_type: string
  classification: 'requirement' | 'need' | 'want' | 'unclassified'
  is_field_relevant: boolean
  is_graduate_capability: boolean
  extraction_method: 'llm' | 'manual'
  confidence: number
  importance_score: number
}

/** Need. */
export interface NeedRow {
  need_id: string
  program_id: string
  statement_th: string
  statement_en: string | null
  rationale_th: string
  /** Every tag the Need carries: one for a single-bucket Need, several for one
   *  Agent 2 merged from Needs of different buckets. */
  ksec_categories: ('K' | 'S' | 'EC' | 'E' | 'C')[]
  bloom_level: string
  member_skill_ids: string[]
  /** The few member skills that carry the Need, for the card's chips. */
  top_skill_ids: string[]
  /** Originals folded into this Need; empty unless it is a merge. */
  merged_from: string[]
  /** The merged Need this one was folded into, or null while it is active. */
  merged_into: string | null
  /** Who made the merge: Agent 2, or the designer at the Need checkpoint. */
  merged_by: 'agent' | 'designer' | null
  /** Set while the designer has taken this Need out of the pool; restoring clears it. */
  excluded_at: string | null
  merge_reason_th: string
  source_evidence_ids: string[]
  stakeholder_coverage: Record<string, number>
  source_stakeholder_types: string[]
  freq: number
  demand_score: number
  is_optional: boolean
  classification_coverage: Record<string, number>
  in_field_skill_count: number
  graduate_capability_skill_count: number
}

export type PloRow = PLO

/** A PLO a merge replaced, newest first once listed. */
export type SupersededRow = SupersededPLO

export type SessionStatus = 'running' | 'suspended' | 'completed' | 'rejected' | 'failed'

/** SessionInfo, plus the bookkeeping the simulation needs. The extra fields
 *  are stripped before a session leaves a handler. */
export interface SessionRow {
  session_id: string
  program_id: string
  thread_id: string
  status: SessionStatus
  current_stage: string | null
  suspended_message: string | null
  created_at: string
  updated_at: string
  /** Epoch ms at which the running step finishes. Null when not running. */
  due_at: number | null
  /** Index into CHECKPOINTS of the checkpoint this run is heading for;
   *  CHECKPOINTS.length means "past the last one", i.e. completing. */
  target: number
  /** Armed by "run ถัดไปล้มเหลว" when this step started. */
  will_fail: boolean
}

export interface MockDb {
  programs: ProgramRow[]
  evidence: EvidenceRow[]
  skills: SkillRow[]
  needs: NeedRow[]
  plos: PloRow[]
  sessions: SessionRow[]
  /** Background stage runs, oldest first — JobInfo as the API sends it. */
  jobs: JobInfo[]
  /** The stage 06 set review, one per program at most. Optional because a db
   *  stored by an earlier build has none; every read treats a missing list as
   *  empty. */
  reviews?: PLOSetReview[]
  /** PLOs replaced by a merge. Optional for the same reason as `reviews`. */
  superseded?: SupersededRow[]
  /** What each review sent back, newest first once listed. Optional for the same reason. */
  feedback?: FeedbackAction[]
  /** The report stored at approval, one per program at most, with the time it was stored.
   *  Optional for the same reason as `reviews`. */
  reports?: Array<{ program_id: string; created_at: string; report: unknown }>
}

export function emptyDb(): MockDb {
  return { programs: [], evidence: [], skills: [], needs: [], plos: [], sessions: [], jobs: [], reviews: [] }
}

// ----------------------------------------------------------------------------
// Persistence
// ----------------------------------------------------------------------------

const DB_KEY = 'mock:db:v1'
const CONTROLS_KEY = 'mock:controls:v1'

function readJson<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Private mode or quota: the mock keeps working in memory for this page.
  }
}

/** What a job still `running` in a stored db is ended with. Same text as the
 *  backend's sweep_orphaned_jobs (api/jobs.py RESTART_MESSAGE_TH). */
const RESTART_MESSAGE_TH = 'backend ถูกปิดระหว่างทำงาน — กดรันใหม่'

/** A db read back from sessionStorage, brought up to date with this build. */
function revive(stored: MockDb | null): MockDb | null {
  if (!stored) return null
  // A db stored by a build that predates jobs has no list.
  const jobs = (stored as Partial<MockDb>).jobs ?? []
  // A mock job runs on a timer in this page, and a reload ends the page with the
  // timer — the mock's counterpart of the backend restarting under a running
  // job, which the real sweep answers the same way: failed, with a reason.
  for (const job of jobs) {
    if (job.status !== 'running') continue
    job.status = 'failed'
    job.error_th = RESTART_MESSAGE_TH
    job.finished_at = utcIso()
  }
  return { ...stored, jobs }
}

let db: MockDb | null = revive(readJson<MockDb>(DB_KEY))

export function hasStoredDb(): boolean {
  return db !== null
}

export function getDb(): MockDb {
  if (!db) db = emptyDb()
  return db
}

export function replaceDb(next: MockDb): void {
  db = next
  saveDb()
}

export function saveDb(): void {
  if (db) writeJson(DB_KEY, db)
}

// ----------------------------------------------------------------------------
// Panel controls
// ----------------------------------------------------------------------------

export interface MockControls {
  scenario: ScenarioName
  /** Realistic delays on (300-900ms, 2-4s for runs) or off (0). */
  latency: boolean
  /** The next API call answers 500. Consumed by that call. */
  failNextRequest: boolean
  /** The next run endpoint or session step fails. Consumed by it. */
  failNextRun: boolean
  /** Stands in for `.env`'s VALIDATION_PROVIDER: off = the agent is disabled
   *  system-wide and GET /plos/validation answers enabled=false. */
  validationEnabled: boolean
}

const DEFAULT_CONTROLS: MockControls = {
  scenario: 'complete',
  latency: true,
  failNextRequest: false,
  failNextRun: false,
  validationEnabled: true,
}

let controls: MockControls = { ...DEFAULT_CONTROLS, ...readJson<Partial<MockControls>>(CONTROLS_KEY) }
const listeners = new Set<() => void>()

export function getControls(): MockControls {
  return controls
}

export function setControls(patch: Partial<MockControls>): void {
  controls = { ...controls, ...patch }
  writeJson(CONTROLS_KEY, controls)
  listeners.forEach((notify) => notify())
}

export function subscribeControls(onChange: () => void): () => void {
  listeners.add(onChange)
  return () => {
    listeners.delete(onChange)
  }
}

/** Read-and-clear, so one armed failure hits exactly one call. */
export function consumeFailNextRequest(): boolean {
  if (!controls.failNextRequest) return false
  setControls({ failNextRequest: false })
  return true
}

export function consumeFailNextRun(): boolean {
  if (!controls.failNextRun) return false
  setControls({ failNextRun: false })
  return true
}

// ----------------------------------------------------------------------------
// Small shared helpers
// ----------------------------------------------------------------------------

/** Naive UTC ISO, the way Pydantic serialises `datetime.utcnow()` values. */
export function nowIso(): string {
  return new Date().toISOString().replace('Z', '')
}

/** UTC ISO with its offset, the way JobInfo sends its timestamps: a browser
 *  reads a naive ISO string as local time, so jobs carry the `+00:00`. */
export function utcIso(): string {
  return new Date().toISOString().replace('Z', '+00:00')
}

export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export function newId(): string {
  return crypto.randomUUID()
}
