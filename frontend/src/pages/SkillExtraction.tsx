import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import NextStageLink from '../components/NextStageLink'
import RunProgress, { LoadingLine, RunFailure } from '../components/RunProgress'
import { SKILL_RUN_PLANS } from '../constants/runPlans'
import { useProgram } from '../hooks/useProgram'
import { useJobs } from '../hooks/useProgramJobs'
import { useReloadOnJobs } from '../hooks/useReloadOnJobs'
import api from '../api/client'
import { startJob, type JobInfo, type JobKind } from '../api/jobs'
import SkillsByStakeholder, {
  type EvidenceMeta,
  type SkillRow,
} from './components/SkillsByStakeholder'
import { ksecLabel, stakeholderLabel } from '../constants/stakeholder'
import { demandPercent } from '../constants/demand'
import DesignerNote from './components/DesignerNote'

/** Which run a click starts. 'all' is the first run: Agent 1, then Agent 2 as a
 *  second job. 'skills' re-extracts and stops at the skill groups. */
type RunKind = 'all' | 'skills'

const RUN_PATH: Record<RunKind, string> = {
  all: 'run',
  skills: 'skills/run',
}

/** The jobs this page shows. `needs_pipeline` is old rows only; new runs are a
 *  skill_extraction job. A need_combination job is Agent 2's: it is not shown
 *  here, only announced. */
const RUN_OF_KIND: Partial<Record<JobKind, RunKind>> = {
  needs_pipeline: 'all',
  skill_extraction: 'skills',
}
const PAGE_KINDS: JobKind[] = ['needs_pipeline', 'skill_extraction']
/** What makes this page reload. Wider than PAGE_KINDS: the page also loads the
 *  Needs (stale banner, Need-count link), and the need_combination job Agent 1
 *  chains into rewrites them without ever being shown here. */
const RELOAD_KINDS: JobKind[] = [...PAGE_KINDS, 'need_combination']

/** `dropped_ungrounded_count` off a finished extraction job's result; 0 when
 *  there is no such job or its run did not finish. */
function droppedCountOf(job: JobInfo | null): number {
  if (job?.status !== 'succeeded') return 0
  const n = (job.result as { dropped_ungrounded_count?: unknown } | null)?.dropped_ungrounded_count
  return typeof n === 'number' ? n : 0
}

/** SkillGroup, the fields this page draws. `ksec` is the bucket: E and C share
 *  `EC`, and clustering never crosses a bucket. */
interface SkillGroupRow {
  group_id: string
  ksec: string
  skill_names: string[]
  skill_frequencies: number[]
  skill_ids: string[]
  evidence_ids: string[]
  demand_score: number
  is_optional: boolean
  stakeholder_types: string[]
}

const BUCKETS = ['K', 'S', 'EC'] as const

/** Only the ids matter here: a Need naming a skill id that is gone is stale. */
interface NeedIds {
  need_id: string
  merged_into: string | null
  member_skill_ids: string[]
}

export default function SkillExtraction() {
  const { programId } = useProgram()
  const [tab, setTab] = useState<'skills' | 'groups'>('skills')
  const [skills, setSkills] = useState<SkillRow[]>([])
  const [groups, setGroups] = useState<SkillGroupRow[]>([])
  const [needs, setNeeds] = useState<NeedIds[]>([])
  const [evidenceById, setEvidenceById] = useState<Record<string, EvidenceMeta>>({})
  const [loading, setLoading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')

  const { running, latestOf, started, refresh } = useJobs()
  // `running` is any job of this program; `mine` is one this page shows.
  const mine = running && PAGE_KINDS.includes(running.kind) ? running : null
  const runKind = mine ? (RUN_OF_KIND[mine.kind] ?? null) : null
  // Agent 2 starts the moment Agent 1's job succeeds, so this notice is what a
  // designer who stayed on this page sees next.
  const agent2Running = running?.kind === 'need_combination'
  const last = latestOf(PAGE_KINDS)
  const droppedCount = droppedCountOf(last)
  // Any job of the program blocks every start button here, not just this page's
  // kinds: the backend allows one writer per program. `starting` covers the gap
  // between the click and the job being known.
  const busy = running !== null || starting

  const fetchAll = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const [skillRes, groupRes, needRes, evidenceRes] = await Promise.all([
        api.get<SkillRow[]>(`/programs/${programId}/needs/skills`),
        api.get<SkillGroupRow[]>(`/programs/${programId}/needs/skill-groups`),
        api.get<NeedIds[]>(`/programs/${programId}/needs/?active_only=true`),
        api.get<(EvidenceMeta & { evidence_id: string })[]>(`/programs/${programId}/evidence/`),
      ])
      setSkills(skillRes.data)
      setGroups(groupRes.data)
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
      setError('โหลดข้อมูลขั้นสกัดทักษะไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }, [programId])

  // Reload once when an extraction or the chained need_combination job ends,
  // whichever way: a failed run may already have replaced the skills.
  const watch = useReloadOnJobs(RELOAD_KINDS, () => void fetchAll())

  // The run is a background job: starting it only records it. Its result lands
  // in the tables, and the reload above picks it up when the job ends.
  const runStage = useCallback(
    async (kind: RunKind) => {
      if (!programId) return
      setStarting(true)
      setError('')
      try {
        const job = await startJob(`/programs/${programId}/needs/${RUN_PATH[kind]}`, {
          note_th: note.trim() || null,
        })
        watch(job)
        started(job)
      } catch (err: unknown) {
        const res = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
        setError(res?.data?.detail ?? 'รันขั้นสกัดทักษะไม่สำเร็จ')
        // A 409 means a job this page has not heard of is running (another tab,
        // or a session): read the list now so the buttons say so too.
        if (res?.status === 409) void refresh()
      } finally {
        setStarting(false)
      }
    },
    [programId, note, watch, started, refresh],
  )

  useEffect(() => { fetchAll() }, [fetchAll])

  /**
   * Needs left behind by an older set of skills.
   *
   * skill_extraction deletes every skill row and mints new ids, so a Need that
   * still names an id no longer on record was built from a previous extraction.
   * The Need page is where the fix is, but the cause is here, so both say so.
   */
  const staleNeedCount = useMemo(() => {
    if (skills.length === 0 || needs.length === 0) return 0
    const live = new Set(skills.map(s => s.skill_id))
    return needs.filter(n => n.member_skill_ids.some(id => !live.has(id))).length
  }, [skills, needs])

  const groupsByBucket = useMemo(
    () =>
      BUCKETS.map(b => ({
        bucket: b,
        rows: groups
          .filter(g => g.ksec === b)
          .sort((x, y) => y.demand_score - x.demand_score),
      })),
    [groups],
  )

  if (!programId) {
    return (
      <div className="mx-auto max-w-2xl py-16 text-center">
        <p className="mb-4 text-pencil">ยังไม่ได้เลือกโปรแกรม</p>
        <Link to="/" className="link">ไปหน้า Intake</Link>
      </div>
    )
  }

  const hasData = skills.length > 0

  return (
    <div className="max-w-4xl">
      <div className="mb-6">
        <p className="eyebrow">ขั้นที่ 3</p>
        <h1 className="page-title mb-1">สกัดทักษะ</h1>
        <p className="text-sm text-pencil">
          ทักษะดิบที่สกัดจาก evidence และกลุ่มทักษะในแต่ละหมวด KSEC — ส่งต่อให้ขั้นวิเคราะห์ Need
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
      {agent2Running && (
        <div className="notice notice-info mb-6">
          สกัดทักษะเสร็จแล้ว — Agent 2 เริ่มวิเคราะห์ Need แล้ว ดูผลที่หน้า{' '}
          <Link to="/need-analysis" className="underline underline-offset-2">วิเคราะห์ Need</Link>
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
            สกัดทักษะและวิเคราะห์ Need
          </button>
        </div>
      ) : (
        <>
          <DesignerNote value={note} onChange={setNote} disabled={busy} />
          <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
            <button
              onClick={() => runStage('skills')}
              disabled={busy}
              title="สกัดทักษะจาก evidence ใหม่ (ไม่แตะ Need ที่มีอยู่)"
              className="btn btn-sm btn-secondary"
            >
              สกัดทักษะใหม่
            </button>
            <Link to="/need-analysis" className="link text-sm">
              ไปหน้าวิเคราะห์ Need ({needs.length})
            </Link>
          </div>

          {staleNeedCount > 0 && (
            <div className="notice notice-warn mb-4">
              Need {staleNeedCount} รายการมาจากทักษะชุดก่อน — รวม Need ใหม่ที่หน้า{' '}
              <Link to="/need-analysis" className="underline underline-offset-2">วิเคราะห์ Need</Link>
            </div>
          )}

          <div className="mb-4 flex flex-wrap gap-1 border-b border-hair-strong">
            {([
              ['skills', `Skill ดิบ (${skills.length})`],
              ['groups', `กลุ่มทักษะ (${groups.length})`],
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
          ) : groups.length === 0 ? (
            <p className="py-8 text-center text-sm text-lead">ยังไม่มีกลุ่มทักษะ — สกัดทักษะใหม่เพื่อจัดกลุ่ม</p>
          ) : (
            <div className="space-y-6">
              {groupsByBucket.map(({ bucket, rows }) => (
                <section key={bucket}>
                  <h2 className="section-title">
                    {ksecLabel(bucket)} <span className="data text-xs text-lead">({rows.length})</span>
                  </h2>
                  {rows.length === 0 ? (
                    <p className="mt-2 text-sm text-lead">ไม่มีกลุ่มในหมวดนี้</p>
                  ) : (
                    <ul className="mt-2 space-y-2">
                      {rows.map(g => (
                        <li key={g.group_id} className="panel p-3">
                          <div className="flex flex-wrap items-start gap-2">
                            <p className="record min-w-0 flex-1 basis-64">
                              {g.skill_names.slice(0, 4).join(' · ')}
                              {g.skill_names.length > 4 && ` +${g.skill_names.length - 4}`}
                            </p>
                            {g.is_optional && <span className="chip chip-neutral shrink-0">เสริม</span>}
                          </div>
                          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-pencil">
                            <span className="data">ทักษะ {g.skill_ids.length}</span>
                            <span className="data">หลักฐาน {g.evidence_ids.length}</span>
                            <span className="data">demand {demandPercent(g.demand_score)}</span>
                            {g.stakeholder_types.length > 0 && (
                              <span>{g.stakeholder_types.map(stakeholderLabel).join(' · ')}</span>
                            )}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              ))}
            </div>
          )}
        </>
      )}

      <NextStageLink
        from="skill_extraction"
        ready={groups.length > 0 && mine === null}
        blockedReason={
          mine !== null
            ? 'รอให้รันเสร็จก่อน — ขั้นวิเคราะห์ Need ต้องอ่านจากกลุ่มทักษะชุดนี้'
            : 'ยังไม่มีกลุ่มทักษะ — สกัดทักษะให้เสร็จก่อน'
        }
      />
    </div>
  )
}
