import { useState, useEffect, useLayoutEffect, useCallback, useMemo, useRef } from 'react'
import { Link } from 'react-router-dom'
import NextStageLink from '../components/NextStageLink'
import RunProgress, { LoadingLine, RunFailure } from '../components/RunProgress'
import { SKILL_RUN_PLANS } from '../constants/runPlans'
import { useProgram } from '../hooks/useProgram'
import { useJobs } from '../hooks/useProgramJobs'
import api from '../api/client'
import { startJob, type JobInfo, type JobKind } from '../api/jobs'
import SkillsByStakeholder, {
  type EvidenceMeta,
  type SkillRow,
} from './components/SkillsByStakeholder'
import NeedCard, { type NeedRow } from './components/NeedCard'
import { scopeVerdict } from '../constants/scope'
import { MAX_CORE_PLOS, MIN_CORE_PLOS, fallbackKind } from '../constants/needPolicy'
import DesignerNote from './components/DesignerNote'

/** Which stage a run covers. 'all' is the first run, where there is nothing to
 * combine yet; the other two are the split re-runs. */
type RunKind = 'all' | 'skills' | 'needs'

const RUN_PATH: Record<RunKind, string> = {
  all: 'run',
  skills: 'skills/run',
  needs: 'combine/run',
}

/** The jobs this page owns, and which run each one is. Which run is on screen
 *  is read off the job, not remembered by the page that clicked: a page opened
 *  mid-run, or after a reload, never clicked anything. */
const RUN_OF_KIND: Partial<Record<JobKind, RunKind>> = {
  needs_pipeline: 'all',
  skill_extraction: 'skills',
  need_combination: 'needs',
}
const PAGE_KINDS: JobKind[] = ['needs_pipeline', 'skill_extraction', 'need_combination']
/** Only an extraction pass can drop a skill for being ungrounded, so a
 *  combine-only run must not reset the count the last extraction reported. */
const EXTRACTION_KINDS: JobKind[] = ['needs_pipeline', 'skill_extraction']

/** `dropped_ungrounded_count` off a finished extraction job's result; 0 when
 *  there is no such job or its run did not finish. */
function droppedCountOf(job: JobInfo | null): number {
  if (job?.status !== 'succeeded') return 0
  const n = (job.result as { dropped_ungrounded_count?: unknown } | null)?.dropped_ungrounded_count
  return typeof n === 'number' ? n : 0
}

export default function SkillExtraction() {
  const { programId } = useProgram()
  const [tab, setTab] = useState<'skills' | 'needs'>('skills')
  const [skills, setSkills] = useState<SkillRow[]>([])
  const [needs, setNeeds] = useState<NeedRow[]>([])
  const [evidenceById, setEvidenceById] = useState<Record<string, EvidenceMeta>>({})
  const [loading, setLoading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')

  const { running, latestOf, started, refresh } = useJobs()
  // `running` is any job of this program; `mine` is one this page shows.
  const mine = running && PAGE_KINDS.includes(running.kind) ? running : null
  const runKind = mine ? (RUN_OF_KIND[mine.kind] ?? null) : null
  const last = latestOf(PAGE_KINDS)
  const droppedCount = droppedCountOf(latestOf(EXTRACTION_KINDS))
  // Any job of the program blocks every start button here, not just this page's
  // kinds: the backend allows one writer per program. `starting` covers the gap
  // between the click and the job being known, so a second click cannot be
  // refused with a 409 about the run it has just started.
  const busy = running !== null || starting

  // Ids of the jobs this page has seen running while it is mounted: the one its
  // own start handed back, and whichever job the shared list shows running. A
  // reload is owed when one of them is later seen to have succeeded. Nothing is
  // compared against a clock — the server's and the browser's may disagree — and
  // a job that finished before the page mounted is covered by the mount load.
  const watching = useRef(new Set<string>())

  const fetchAll = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const [skillRes, needRes, evidenceRes] = await Promise.all([
        api.get<SkillRow[]>(`/programs/${programId}/needs/skills`),
        api.get<NeedRow[]>(`/programs/${programId}/needs/`),
        api.get<(EvidenceMeta & { evidence_id: string })[]>(`/programs/${programId}/evidence/`),
      ])
      setSkills(skillRes.data)
      setNeeds(needRes.data)
      setEvidenceById(
        Object.fromEntries(
          evidenceRes.data.map(e => [
            e.evidence_id,
            {
              source_name: e.source_name,
              stakeholder_type: e.stakeholder_type,
              classification: e.classification,
            },
          ]),
        ),
      )
    } catch {
      setError('โหลดข้อมูล Stage 3 ไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }, [programId])

  // The run is a background job: starting it only records it. Its result lands
  // in the tables, and the reload below picks it up when the job succeeds.
  const runStage = useCallback(
    async (kind: RunKind) => {
      if (!programId) return
      setStarting(true)
      setError('')
      try {
        const job = await startJob(`/programs/${programId}/needs/${RUN_PATH[kind]}`, {
          note_th: note.trim() || null,
        })
        watching.current.add(job.job_id)
        started(job)
      } catch (err: unknown) {
        const res = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
        setError(res?.data?.detail ?? 'รัน Stage 3 ไม่สำเร็จ')
        // A 409 means a job this page has not heard of is running (another tab,
        // or a session): read the list now so the buttons say so too.
        if (res?.status === 409) void refresh()
      } finally {
        setStarting(false)
      }
    },
    [programId, note, started, refresh],
  )

  useEffect(() => { fetchAll() }, [fetchAll])

  // Reload once when a job this page watched running is seen to have succeeded.
  // The effects are keyed on ids and a status — primitives — because the job
  // objects get a new identity on every poll, and an effect keyed on them would
  // reload every two seconds. Layout effects, not passive ones: when the result
  // arrives the run screen is replaced in the same commit, and a passive effect
  // would let the browser paint the previous data (or the empty state, with a
  // live start button) for a moment before the reload put the loading line up.
  const runningId = running && PAGE_KINDS.includes(running.kind) ? running.job_id : ''
  const lastId = last?.job_id ?? ''
  const lastStatus = last?.status ?? ''
  // Another program's jobs are not this one's to reload for.
  useLayoutEffect(() => {
    watching.current.clear()
  }, [programId])
  useLayoutEffect(() => {
    if (runningId) watching.current.add(runningId)
  }, [runningId])
  useLayoutEffect(() => {
    // Forgotten as soon as it has ended, whichever way: a failed job changed no rows.
    if (lastStatus === 'running' || !watching.current.delete(lastId)) return
    if (lastStatus === 'succeeded') void fetchAll()
  }, [lastId, lastStatus, fetchAll])

  /**
   * Needs left behind by an older set of skills.
   *
   * skill_extraction deletes every skill row and mints new ids, so a Need that
   * still names an id no longer on record was built from a previous extraction.
   * Its trace would come back empty, which reads as a bug rather than as stale
   * data — hence the banner.
   */
  /**
   * Needs the scope guard will hold back at plo_synthesis.
   *
   * Derived here rather than read off a response, the same way the report
   * derives it: the guard runs at synthesis, so nothing has judged these rows
   * yet and no endpoint returns a verdict. Saying it at this checkpoint is the
   * point of saying it at all — the fix is to edit the scope statement and
   * re-extract, and the button for that is on this page. Discovered at the
   * report instead, the same fix costs every synthesis call already paid for.
   */
  const guardedNeedCount = useMemo(
    () => needs.filter(n => scopeVerdict(n) !== 'in_scope').length,
    [needs],
  )

  /**
   * How many core PLOs this Need set will actually yield, against the 6-10 band.
   *
   * plo_synthesis drops out-of-scope Needs *before* it applies the ceiling, so
   * the number that lands in the curriculum is the in-scope core count capped at
   * MAX_CORE_PLOS — not the core count on its own, which is what the list above
   * shows and what a designer would otherwise count by eye.
   *
   * The pipeline already knows this and says so twice, both times only to the
   * server log: need_combination warns when the core count is short, and
   * plo_synthesis warns again after the guard has run, naming the guard as the
   * cause. Its own comment says "the designer must add more at the review
   * checkpoint" — this is that checkpoint, and until now it said nothing.
   */
  const coreOutlook = useMemo(() => {
    const core = needs.filter(n => !n.is_optional)
    const surviving = core.filter(n => scopeVerdict(n) === 'in_scope').length
    return {
      core: core.length,
      guarded: core.length - surviving,
      projected: Math.min(surviving, MAX_CORE_PLOS),
      unwritten: needs.filter(n => fallbackKind(n.statement_th)).length,
    }
  }, [needs])

  const staleNeedCount = useMemo(() => {
    if (skills.length === 0 || needs.length === 0) return 0
    const live = new Set(skills.map(s => s.skill_id))
    return needs.filter(n => n.member_skill_ids.some(id => !live.has(id))).length
  }, [skills, needs])

  if (!programId) {
    return (
      <div className="mx-auto max-w-2xl py-16 text-center">
        <p className="mb-4 text-pencil">ยังไม่ได้เลือกโปรแกรม</p>
        <Link to="/" className="link">ไปหน้า Intake</Link>
      </div>
    )
  }

  const hasData = skills.length > 0 || needs.length > 0

  return (
    <div className="max-w-4xl">
      <div className="mb-6">
        <p className="eyebrow">ขั้นที่ 3</p>
        <h1 className="page-title mb-1">สกัดทักษะและรวมเป็น Need</h1>
        <p className="text-sm text-pencil">
          ทักษะดิบที่สกัดจาก evidence และ Need ที่กลั่นจากทักษะเหล่านั้น
        </p>
        <p className="data mt-1 text-xs text-lead">{programId}</p>
      </div>

      {error && (
        <div className="notice notice-error mb-6">{error}</div>
      )}
      {last?.status === 'failed' && (
        <div className="mb-6">
          <RunFailure job={last} />
        </div>
      )}

      {/* A run in progress comes before the loading line: what a load would
          show is about to be replaced, and a page opened mid-run should say so
          at once rather than after its own read finishes. */}
      {mine && runKind ? (
        <RunProgress key={mine.job_id} plan={SKILL_RUN_PLANS[runKind]} since={Date.parse(mine.created_at)} />
      ) : loading ? (
        <LoadingLine />
      ) : !hasData ? (
        <div className="panel border-dashed px-6 py-12 text-center">
          <p className="font-display mb-1 text-lg text-graphite">ยังไม่มีทักษะที่สกัดได้</p>
          <p className="mb-6 text-sm text-pencil">กดปุ่มด้านล่างเพื่อสกัดทักษะจาก evidence ที่มีอยู่</p>
          <div className="mx-auto mb-2 max-w-md">
            <DesignerNote value={note} onChange={setNote} />
          </div>
          <button
            onClick={() => runStage('all')}
            disabled={busy}
            className="btn btn-primary"
          >
            สกัดทักษะและรวม Need
          </button>
        </div>
      ) : (
        <>
          <DesignerNote value={note} onChange={setNote} disabled={busy} />
          <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1">
              {/* Two entry points, not one: re-extracting is the expensive
                  per-evidence LLM pass, while re-combining only re-clusters
                  what is already on record. */}
              <button
                onClick={() => runStage('skills')}
                disabled={busy}
                title="สกัดทักษะจาก evidence ใหม่ (ไม่แตะ Need ที่มีอยู่)"
                className="btn btn-sm btn-secondary"
              >
                สกัดทักษะใหม่
              </button>
              <span className="text-xs text-lead" aria-hidden="true">·</span>
              <button
                onClick={() => runStage('needs')}
                disabled={busy}
                title="รวมทักษะที่มีอยู่เป็น Need ใหม่ (ไม่สกัดทักษะซ้ำ)"
                className="btn btn-sm btn-secondary"
              >
                รวม Need ใหม่
              </button>
            </div>
          </div>

          <div className="mb-4 flex flex-wrap gap-1 border-b border-hair-strong">
            {([
              ['skills', `Skill ดิบ (${skills.length})`],
              ['needs', `Need (${needs.length})`],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`-mb-px rounded-t-[3px] px-4 py-2 text-sm font-medium transition-colors ${
                  tab === key
                    ? 'border-b-2 border-stamp text-stamp'
                    : 'border-b-2 border-transparent text-pencil hover:text-graphite'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === 'skills' ? (
            <SkillsByStakeholder
              skills={skills}
              evidenceById={evidenceById}
              droppedCount={droppedCount}
            />
          ) : needs.length === 0 ? (
            <p className="py-8 text-center text-sm text-lead">ยังไม่มี Need — รัน Skill Extraction ก่อน</p>
          ) : (
            <div className="space-y-3">
              {staleNeedCount > 0 && (
                <div className="notice notice-warn flex flex-wrap items-center gap-3">
                  <span className="min-w-0 flex-1">
                    Need {staleNeedCount} รายการมาจากทักษะชุดก่อน — กด “รวม Need ใหม่”
                    เพื่อรวมใหม่จากทักษะปัจจุบัน
                  </span>
                  <button
                    onClick={() => runStage('needs')}
                    disabled={busy}
                    className="btn btn-sm btn-secondary"
                  >
                    รวม Need ใหม่
                  </button>
                </div>
              )}
              {/* Placed above the guard notice, which explains what to do about
                  the Needs this count is missing. */}
              <div
                className={`notice ${
                  coreOutlook.projected < MIN_CORE_PLOS
                    ? 'notice-warn'
                    : 'border-hair-strong bg-sunk text-graphite'
                }`}
              >
                <p>
                  จะได้ PLO หลัก <span className="data font-semibold">{coreOutlook.projected}</span> ข้อ
                  {' '}· เกณฑ์ {MIN_CORE_PLOS}-{MAX_CORE_PLOS} ข้อ
                  {coreOutlook.projected < MIN_CORE_PLOS && ' — ต่ำกว่าเกณฑ์'}
                </p>
                <p className="mt-1 text-xs opacity-85">
                  Need หลัก {coreOutlook.core} ข้อ
                  {coreOutlook.guarded > 0 && ` · ตัวกรองขอบเขตกันออก ${coreOutlook.guarded} ข้อ`}
                  {coreOutlook.core - coreOutlook.guarded > MAX_CORE_PLOS &&
                    ` · เกิน ${MAX_CORE_PLOS} ข้อ ระบบใช้เฉพาะ ${MAX_CORE_PLOS} ข้อที่ demand สูงสุด`}
                  {coreOutlook.unwritten > 0 &&
                    ` · เขียนไม่สำเร็จ ${coreOutlook.unwritten} ข้อ (นับรวมอยู่ด้วย)`}
                </p>
              </div>
              {guardedNeedCount > 0 && (
                <div className="notice notice-error">
                  <p>
                    <span className="data font-semibold">{guardedNeedCount}</span> จาก {needs.length}{' '}
                    ข้อจะไม่ถูกส่งต่อไป PLO synthesis เพราะอยู่นอกขอบเขตของหลักสูตร — ป้ายบนการ์ด
                    บอกเหตุผลรายใบ กด “ดูที่มา” เพื่อดูว่าทักษะตัวไหนทำให้ถูกกัน
                  </p>
                  <p className="mt-1.5">
                    <span className="font-semibold">ถ้าตัดสินผิด:</span> แก้ “ขอบเขตของหลักสูตร” ที่หน้า{' '}
                    <Link to="/intake" className="underline underline-offset-2">
                      Intake
                    </Link>{' '}
                    แล้วกด <span className="font-semibold">สกัดทักษะใหม่</span> ด้านบน — ทั้งโปรแกรมถูกสกัดใหม่
                    (ระบบไม่รันให้เอง ทุกขั้นต้องผ่านการอนุมัติ)
                  </p>
                  <p className="mt-1.5">
                    <span className="font-semibold">ถ้าตัดสินถูกแต่ยังอยากได้:</span> เลือกมันที่หน้า
                    PLO Synthesis แล้วกด “รวมเป็น PLO เดียว” — ตรงนั้นไม่กัน
                  </p>
                </div>
              )}
              {needs.map(n => (
                <NeedCard key={n.need_id} programId={programId} need={n} />
              ))}
            </div>
          )}
        </>
      )}

      {/* Needs, not skills: plo_synthesis drafts one PLO per Need and never
          reads the skill rows. A run that extracted skills and combined nothing
          has not produced what the next stage needs. */}
      <NextStageLink
        from="skill_extraction"
        ready={Boolean(programId) && needs.length > 0 && mine === null}
        blockedReason={
          mine !== null
            ? 'รอให้รันเสร็จก่อน — ขั้นสังเคราะห์ PLO ต้องอ่านจาก Need ชุดนี้'
            : 'ยังไม่มี Need — รันสกัดทักษะและรวม Need ให้เสร็จก่อน'
        }
      />
    </div>
  )
}
