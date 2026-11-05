import { useState, useEffect, useCallback, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useProgram } from '../hooks/useProgram'
import { useJobs } from '../hooks/useProgramJobs'
import { useReloadOnJobs } from '../hooks/useReloadOnJobs'
import RunProgress, { LoadingLine, RunFailure } from '../components/RunProgress'
import { PLO_REPORT_PLAN, PLO_REVIEW_PLAN } from '../constants/runPlans'
import api from '../api/client'
import { startJob, type JobKind } from '../api/jobs'
import { BLOOM_ORDER, bloomLabel } from '../constants/bloom'
import { ksecLabel, stakeholderLabel } from '../constants/stakeholder'
import FeedbackTrail from './components/FeedbackTrail'
import type { SupersededPLO } from '../types/plo'
import type {
  FeedbackAction,
  KsecFinding,
  PLOReviewResponse,
  PLOSetReview,
} from '../types/ploReview'

/** The job kinds whose runs this page shows. */
const PAGE_KINDS: JobKind[] = ['plo_review']
/** The jobs that change what this page draws, whichever page started them: the
 *  review is a reading of the PLOs and the Needs, so a synthesis, a re-check or
 *  a new set of Needs all leave it describing a set that moved. `plo_report` is
 *  here for the approval this page starts: its success sends the designer on. */
const RELOAD_KINDS: JobKind[] = [
  'plo_review',
  'plo_report',
  'plo_synthesis',
  'plo_revalidate',
  'needs_pipeline',
  'skill_extraction',
  'need_combination',
]

const KSEC_DOMAINS = ['K', 'S', 'E', 'C'] as const

const KSEC_FLAG_TH: Record<string, string> = {
  all_k: 'ทั้งชุดเป็นความรู้ (K) ล้วน',
  no_e_or_c: 'ไม่มี PLO ด้านจริยธรรม (E) หรือคุณลักษณะบุคคล (C)',
}

const BLOOM_FLAG_TH: Record<string, string> = {
  below_apply_majority: 'PLO เกินครึ่งอยู่ต่ำกว่าระดับประยุกต์ใช้',
}

const EXCLUSION_TH: Record<string, string> = {
  lost_on_demand: 'ไม่ติดอันดับ demand',
  out_of_scope: 'อยู่นอกขอบเขตหลักสูตร',
  unwritten: 'ประโยค Need ยังไม่ได้เขียน',
}

const CODE_ONLY_REASON_TH: Record<string, string> = {
  disabled: '(ปิดการตรวจด้วย agent ไว้ใน .env)',
  failed: '(agent ตอบไม่สำเร็จ)',
  timeout: '(agent ใช้เวลาเกินกำหนด)',
}

const DEGREE_TH: Record<string, string> = {
  bachelor: 'ปริญญาตรี',
  master: 'ปริญญาโท',
  doctoral: 'ปริญญาเอก',
}

/** `created_at` arrives naive-UTC, with no offset. `Date.parse` would read that
 *  as local time, so the zone is made explicit first. */
function formatCreatedAt(iso: string): string {
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso)
  const at = new Date(hasZone ? iso : `${iso}Z`)
  if (Number.isNaN(at.getTime())) return iso
  return at.toLocaleString('th-TH', { dateStyle: 'medium', timeStyle: 'short' })
}

/** `['S', 'E']` as `S+E`; nothing as a dash. */
const domains = (list: string[]): string => (list.length ? list.join('+') : '—')

interface RunError {
  text: string
  status: number | undefined
}

export default function PloReview() {
  const { programId } = useProgram()
  // Tagged with the program it was read for, so another program's review is
  // never drawn while this one loads.
  const [read, setRead] = useState<{ programId: string; response: PLOReviewResponse } | null>(null)
  const data = read?.programId === programId ? read.response : null
  const [loadError, setLoadError] = useState('')
  // The send-back trail and the history it points into. Secondary: a failed read leaves them empty.
  const [trail, setTrail] = useState<{ programId: string; feedback: FeedbackAction[]; superseded: SupersededPLO[] } | null>(null)
  const [starting, setStarting] = useState(false)
  const [runError, setRunError] = useState<RunError | null>(null)
  const navigate = useNavigate()
  // The approval job this page started; its success is what navigates on, and
  // a report run some other page started must not pull the designer away.
  const approvalJob = useRef<string | null>(null)

  const { running, latestOf, started, refresh } = useJobs()
  // `running` is any job of this program; `mine` is the review this page shows.
  const mine = running?.kind === 'plo_review' ? running : null
  const last = latestOf(PAGE_KINDS)
  // The approval's own failure; the report is stored by it, so it is this page's.
  const lastReport = latestOf(['plo_report'])
  const approving = running?.kind === 'plo_report' ? running : null
  // Any job of the program blocks the button: one writer per program.
  const busy = running !== null || starting

  // The newest read wins: a slow answer for a program the designer has already
  // left must not overwrite the one now on screen.
  const latestRead = useRef(0)
  const fetchData = useCallback(async () => {
    if (!programId) return
    const mineRead = ++latestRead.current
    setLoadError('')
    try {
      const [res, fb, sup] = await Promise.all([
        api.get<PLOReviewResponse>(`/programs/${programId}/plos/review`),
        api.get<FeedbackAction[]>(`/programs/${programId}/plos/feedback`).catch(() => ({ data: [] as FeedbackAction[] })),
        api.get<SupersededPLO[]>(`/programs/${programId}/plos/superseded`).catch(() => ({ data: [] as SupersededPLO[] })),
      ])
      if (mineRead === latestRead.current) {
        setRead({ programId, response: res.data })
        setTrail({ programId, feedback: fb.data, superseded: sup.data })
      }
    } catch {
      if (mineRead === latestRead.current) {
        setLoadError('โหลดผลตรวจไม่สำเร็จ ตรวจว่า API ทำงานอยู่ แล้วลองใหม่')
      }
    }
  }, [programId])

  const watch = useReloadOnJobs(RELOAD_KINDS, (job) => {
    void fetchData()
    if (job.kind === 'plo_report' && job.job_id === approvalJob.current) {
      approvalJob.current = null
      if (job.status === 'succeeded') navigate('/plo-report')
    }
  })

  const runReview = useCallback(async () => {
    if (!programId) return
    setStarting(true)
    setRunError(null)
    try {
      const job = await startJob(`/programs/${programId}/plos/review/run`)
      watch(job)
      started(job)
    } catch (err: unknown) {
      const res = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
      setRunError({ text: res?.data?.detail ?? 'ตรวจชุด PLO ไม่สำเร็จ', status: res?.status })
      // A 409 means a job this page has not heard of is running: read the list
      // now so the button says so too.
      if (res?.status === 409) void refresh()
    } finally {
      setStarting(false)
    }
  }, [programId, watch, started, refresh])

  // Approving stores the report (POST /plos/report/run) and then the report page
  // reads it; graph-session approval stays on the Pipeline page.
  const approve = useCallback(async () => {
    if (!programId) return
    setStarting(true)
    setRunError(null)
    try {
      const job = await startJob(`/programs/${programId}/plos/report/run`)
      approvalJob.current = job.job_id
      watch(job)
      started(job)
    } catch (err: unknown) {
      const res = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
      setRunError({ text: res?.data?.detail ?? 'อนุมัติชุด PLO ไม่สำเร็จ', status: res?.status })
      if (res?.status === 409) void refresh()
    } finally {
      setStarting(false)
    }
  }, [programId, watch, started, refresh])

  useEffect(() => {
    void fetchData()
  }, [fetchData])

  if (!programId) {
    return (
      <div className="py-16 text-center">
        <p className="mb-3 text-pencil">ยังไม่ได้เลือกหลักสูตร</p>
        <Link to="/" className="link">
          เลือกจากรายการหลักสูตร
        </Link>
      </div>
    )
  }

  const review = data?.review ?? null
  const dropped = droppedNotice(review?.dropped_findings)
  const agentOff = data?.review_enabled === false
  const trailNow = trail?.programId === programId ? trail : null

  return (
    <div className="space-y-6">
      <header>
        <p className="eyebrow">ขั้นที่ 6</p>
        <h1 className="page-title">ตรวจคุณภาพชุด PLO</h1>
        <p className="mt-1 text-sm text-pencil">
          QA agent อ่าน PLO ทั้งชุดที่ทำเสร็จแล้ว แล้วให้คำแนะนำ — ข้อที่ตรงกันและแก้ได้จะถูกส่งกลับไปแก้ให้ พร้อมบันทึกว่าแก้อะไร
        </p>
      </header>

      {loadError && <p className="notice notice-error">{loadError}</p>}
      {runError && (
        <p className="notice notice-error">
          {runError.text}
          {runError.status === 422 && (
            <>
              {' '}
              <Link to="/plo-synthesis" className="link">
                ไปสังเคราะห์ PLO
              </Link>
            </>
          )}
        </p>
      )}
      {last?.status === 'failed' && <RunFailure job={last} />}
      {lastReport?.status === 'failed' && <RunFailure job={lastReport} />}

      {approving ? (
        <RunProgress key={approving.job_id} plan={PLO_REPORT_PLAN} since={Date.parse(approving.created_at)} />
      ) : mine ? (
        <RunProgress key={mine.job_id} plan={PLO_REVIEW_PLAN} since={Date.parse(mine.created_at)} />
      ) : data === null && !loadError ? (
        <LoadingLine />
      ) : review ? (
        <>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <StatusLine review={review} />
            <button onClick={runReview} disabled={busy} className="btn btn-secondary btn-sm ml-auto">
              ตรวจใหม่
            </button>
          </div>
          {agentOff && (
            <p className="text-sm text-pencil">ปิดการตรวจด้วย agent ไว้ — กดตรวจจะได้ผลจากโค้ดอย่างเดียว</p>
          )}

          {data?.stale && (
            <p className="notice notice-warn">ชุด PLO เปลี่ยนหลังการตรวจ — ตรวจใหม่ก่อนอนุมัติ</p>
          )}

          {(review.runs_requested ?? 1) > 1 && runsOf(review) === 1 && (
            <p className="notice notice-warn">ได้ผลรอบเดียว ยังไม่ได้ยืนยันซ้ำ</p>
          )}

          {dropped && <p className="notice notice-warn">{dropped}</p>}

          {review.summary_th && <p className="record text-base">{review.summary_th}</p>}
          {isVoted(review) && review.summary_th && (
            <p className="text-sm text-pencil">สรุปจากรอบที่ตรงกับผลรวมมากที่สุด</p>
          )}

          {trailNow && (
            <FeedbackTrail
              feedback={trailNow.feedback}
              superseded={trailNow.superseded}
              review={review}
            />
          )}

          <div className="panel flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4">
            <p className="min-w-0 flex-1 text-sm text-pencil">
              อ่านผลตรวจและตรวจ PLO ให้พอใจแล้วอนุมัติ — ระบบจะเก็บรายงานชุดนี้ไว้เป็นฉบับสุดท้าย
            </p>
            <button
              onClick={approve}
              disabled={busy || data?.stale === true}
              className="btn btn-primary"
            >
              อนุมัติชุด PLO และออกรายงาน
            </button>
          </div>

          <Overview review={review} />
          <Redundancies review={review} />
          <KsecSection review={review} />
          <BloomSection review={review} />
          <UnusedNeeds review={review} />
          <BelowThreshold review={review} />

          {review.tool_calls.length > 0 && (
            <details className="border-t border-hair pt-4">
              <summary className="cursor-pointer text-sm text-pencil">
                agent ไปดูอะไรมาบ้าง ({review.tool_calls.length})
              </summary>
              <ul className="mt-2 space-y-1">
                {review.tool_calls.map((c, i) => (
                  <li key={i} className="data break-words text-xs text-pencil">
                    {c.tool} · {c.arg}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      ) : (
        !loadError && (
          <div className="panel px-6 py-12 text-center">
            <p className="record text-lg">ยังไม่ได้ตรวจชุด PLO นี้</p>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
              <button onClick={runReview} disabled={busy} className="btn btn-primary">
                ตรวจชุด PLO
              </button>
            </div>
            {agentOff && (
              <p className="mt-3 text-sm text-pencil">ปิดการตรวจด้วย agent ไว้ — กดตรวจจะได้ผลจากโค้ดอย่างเดียว</p>
            )}
          </div>
        )
      )}
    </div>
  )
}

const DROPPED_LABEL_TH: Record<string, string> = {
  redundancy: 'ความซ้ำซ้อน',
  ksec: 'หมวด KSEC',
  bloom: 'ระดับ Bloom',
  unused: 'Need ที่ไม่ได้เป็น PLO',
}

/** The warning for agent entries the code refused, or null when none were. */
function droppedNotice(dropped: Record<string, number> | undefined): string | null {
  const entries = Object.entries(dropped ?? {}).filter(([, n]) => n > 0)
  if (entries.length === 0) return null
  const total = entries.reduce((sum, [, n]) => sum + n, 0)
  const parts = entries.map(([kind, n]) => `${DROPPED_LABEL_TH[kind] ?? kind} ${n}`).join(', ')
  return `ระบบตัดข้อเสนอของ agent ที่ไม่ผ่านกติกาออก ${total} ข้อ (${parts}) — ข้อความสรุปอาจยังพูดถึงข้อที่ถูกตัด`
}

const runsOf = (r: PLOSetReview): number => r.runs_succeeded ?? 1
const isVoted = (r: PLOSetReview): boolean => runsOf(r) >= 2
/** Does a finding meet the review's agreement threshold? Old rows: always. */
const isMain = (agreed: number | undefined, r: PLOSetReview): boolean =>
  (agreed ?? 1) >= (r.agreement_threshold ?? 1)

/** "ตรงกัน 2/3" — only on a review voted over several runs. */
function AgreementChip({ agreed, review }: { agreed: number | undefined; review: PLOSetReview }) {
  if (!isVoted(review)) return null
  return (
    <span className="chip chip-neutral ml-2">
      ตรงกัน {agreed ?? 1}/{runsOf(review)}
    </span>
  )
}

/** Who made the review, and when. A code-only review says so and why: it is the
 *  same page with fewer opinions on it, and the designer should not mistake the
 *  missing ones for a clean bill of health. */
function StatusLine({ review }: { review: PLOSetReview }) {
  const when = formatCreatedAt(review.created_at)
  if (review.reviewed_by === 'agent') {
    return (
      <p className="text-sm text-pencil">
        ตรวจโดย agent · {review.model} · {when}
        {isVoted(review) &&
          ` · ตรวจ ${runsOf(review)} รอบ แสดงเฉพาะข้อที่ตรงกันอย่างน้อย ${review.agreement_threshold ?? 1} รอบ`}
      </p>
    )
  }
  const why = review.code_only_reason ? CODE_ONLY_REASON_TH[review.code_only_reason] : undefined
  return (
    <p className="text-sm text-pencil">
      <span className="font-medium text-graphite">ตรวจด้วยโค้ดอย่างเดียว</span>
      {why && ` ${why}`} · {when}
    </p>
  )
}

function Overview({ review }: { review: PLOSetReview }) {
  const { ksec_coverage: ksec, bloom_histogram: bloom } = review
  const levels = [
    ...BLOOM_ORDER,
    // A level this build does not know still counts: shown after the known ones.
    ...Object.keys(bloom.counts).filter((k) => !(BLOOM_ORDER as readonly string[]).includes(k)),
  ]
  const opinions = [review.coverage_th, review.bloom_distribution_th].filter(Boolean)

  return (
    <section className="border-t border-hair pt-5" aria-labelledby="overview-heading">
      <h2 id="overview-heading" className="section-title">
        ภาพรวมทั้งชุด
      </h2>
      <p className="mt-1 text-xs text-lead">ตัวเลขนับโดยระบบ (รวม PLO เสริม)</p>

      <div className="mt-3 space-y-4">
        <div>
          <ul className="flex flex-wrap items-center gap-x-5 gap-y-2">
            {KSEC_DOMAINS.map((k) => (
              <li key={k} className="flex items-baseline gap-1.5">
                <span className="data text-sm font-semibold text-graphite">{k}</span>
                <span className="data text-lg leading-none text-graphite">{ksec.counts[k] ?? 0}</span>
                {ksec.missing.includes(k) && <span className="chip chip-mandate">ไม่มี</span>}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-lead">
            K ความรู้ · S ทักษะวิชาชีพ · E จริยธรรม · C คุณลักษณะบุคคล
          </p>
          {ksec.flags.length > 0 && (
            <ul className="mt-2 space-y-1">
              {ksec.flags.map((f) => (
                <li key={f} className="text-sm text-marker-ink">
                  <span className="chip chip-marker mr-1.5">ข้อสังเกต</span>
                  {KSEC_FLAG_TH[f] ?? f}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <ul className="flex flex-wrap items-baseline gap-x-5 gap-y-2">
            {levels.map((level) => (
              <li key={level} className="flex items-baseline gap-1.5">
                <span className="text-sm text-pencil">{bloomLabel(level)}</span>
                <span className="data text-lg leading-none text-graphite">{bloom.counts[level] ?? 0}</span>
              </li>
            ))}
          </ul>
          {bloom.degree_level && (
            <p className="mt-1.5 text-xs text-lead">
              ระดับปริญญา: {DEGREE_TH[bloom.degree_level] ?? bloom.degree_level}
            </p>
          )}
          {bloom.flags.length > 0 && (
            <ul className="mt-2 space-y-1">
              {bloom.flags.map((f) => (
                <li key={f} className="text-sm text-marker-ink">
                  <span className="chip chip-marker mr-1.5">ข้อสังเกต</span>
                  {BLOOM_FLAG_TH[f] ?? f}
                </li>
              ))}
            </ul>
          )}
        </div>

        {opinions.length > 0 && (
          <div className="border-l-2 border-hair-strong bg-sunk px-3 py-2">
            <p className="eyebrow">ความเห็นของ agent</p>
            {opinions.map((text) => (
              <p key={text} className="mt-1 text-sm text-pencil">
                {text}
              </p>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

function Redundancies({ review }: { review: PLOSetReview }) {
  const groups = review.redundancies.filter((f) => isMain(f.agreed_runs, review))
  return (
    <section className="border-t border-hair pt-5" aria-labelledby="redundancy-heading">
      <h2 id="redundancy-heading" className="section-title">
        ความซ้ำซ้อน
      </h2>
      {groups.length === 0 ? (
        <p className="mt-2 text-sm text-pencil">ไม่พบ PLO ที่ซ้ำกัน</p>
      ) : (
        <>
          <ul className="mt-3 divide-y divide-hair rounded-[4px] border border-hair bg-sunk">
            {groups.map((g, i) => (
              <li key={i} className="px-4 py-3">
                <p className="data text-sm font-semibold text-graphite">
                  {g.plo_ids.join(' · ')}
                  <AgreementChip agreed={g.agreed_runs} review={review} />
                </p>
                <p className="mt-1 text-sm text-pencil">{g.reason_th}</p>
                {g.suggestion_th && (
                  <p className="mt-1 text-sm text-graphite">ข้อเสนอ: {g.suggestion_th}</p>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-sm text-pencil">
            รวม PLO ที่ซ้ำได้โดยรวม Need ที่หน้า{' '}
            <Link to="/plo-synthesis" className="link">
              สังเคราะห์ PLO
            </Link>
          </p>
        </>
      )}
    </section>
  )
}

function KsecTable({ rows, review }: { rows: KsecFinding[]; review: PLOSetReview }) {
  return (
    <div className="overflow-x-auto">
      <table className="table min-w-[32rem]">
        <thead>
          <tr>
            <th>PLO</th>
            <th>หมวดปัจจุบัน</th>
            <th>หมวดที่เสนอ</th>
            <th>เหตุผล</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.plo_id}>
              <td className="data whitespace-nowrap align-top font-semibold text-graphite">{r.plo_id}</td>
              <td className="data whitespace-nowrap align-top">{domains(r.current)}</td>
              <td className="align-top">
                <span className="data whitespace-nowrap">{domains(r.suggested)}</span>
                {!r.agrees && <span className="chip chip-marker ml-2">ไม่ตรง</span>}
                {!r.agrees && <AgreementChip agreed={r.agreed_runs} review={review} />}
              </td>
              <td className="align-top text-pencil">{r.reason_th}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function KsecSection({ review }: { review: PLOSetReview }) {
  const rows = review.ksec
  // The ones that disagree are what the designer came for; the rest are proof
  // the check ran, so they sit behind a fold.
  const differing = rows.filter((r) => !r.agrees && isMain(r.agreed_runs, review))
  const agreeing = rows.filter((r) => r.agrees)
  return (
    <section className="border-t border-hair pt-5" aria-labelledby="ksec-heading">
      <h2 id="ksec-heading" className="section-title">
        หมวดสมรรถนะรายข้อ (KSEC)
      </h2>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-pencil">ไม่มีข้อมูล KSEC</p>
      ) : (
        <div className="mt-3 space-y-3">
          {differing.length > 0 && <KsecTable rows={differing} review={review} />}
          {agreeing.length > 0 && (
            <details>
              <summary className="cursor-pointer text-sm text-pencil">
                ตรงกับหมวดเดิม {agreeing.length} ข้อ
              </summary>
              <div className="mt-2">
                <KsecTable rows={agreeing} review={review} />
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  )
}

function BloomSection({ review }: { review: PLOSetReview }) {
  const rows = review.bloom.filter((b) => isMain(b.agreed_runs, review))
  return (
    <section className="border-t border-hair pt-5" aria-labelledby="bloom-heading">
      <h2 id="bloom-heading" className="section-title">
        ระดับ Bloom รายข้อ
      </h2>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-pencil">ระดับ Bloom ทุกข้อเหมาะกับกริยาและระดับปริญญา</p>
      ) : (
        <ul className="mt-3 divide-y divide-hair rounded-[4px] border border-hair bg-sunk">
          {rows.map((b) => (
            <li key={b.plo_id} className="px-4 py-3">
              <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
                <span className="data font-semibold text-graphite">{b.plo_id}</span>
                <span className="data text-pencil">{bloomLabel(b.declared)}</span>
                {b.suggested_level && b.suggested_level !== b.declared && (
                  <>
                    <span aria-hidden="true" className="text-lead">
                      →
                    </span>
                    <span className="sr-only">ควรเป็น</span>
                    <span className="data text-graphite">{bloomLabel(b.suggested_level)}</span>
                  </>
                )}
                <AgreementChip agreed={b.agreed_runs} review={review} />
              </p>
              {b.reason_th && <p className="mt-1 text-sm text-pencil">{b.reason_th}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function UnusedNeeds({ review }: { review: PLOSetReview }) {
  const needs = review.unused_needs
  return (
    <section className="border-t border-hair pt-5" aria-labelledby="unused-heading">
      <h2 id="unused-heading" className="section-title">
        Need สำคัญที่ไม่ได้เป็น PLO
      </h2>
      {needs.length === 0 ? (
        <p className="mt-2 text-sm text-pencil">ไม่มี Need สำคัญที่ตกหล่น</p>
      ) : (
        <ul className="mt-3 divide-y divide-hair rounded-[4px] border border-hair bg-sunk">
          {needs.map((n) => (
            <li key={n.need_id} className="px-4 py-3">
              <p className="record text-base">{n.statement_th}</p>
              <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-pencil">
                <span className="data">demand {n.demand_score.toFixed(2)}</span>
                <span>{n.ksec_categories.map(ksecLabel).join(' + ')}</span>
                {n.stakeholder_types.length > 0 && (
                  <span>{n.stakeholder_types.map(stakeholderLabel).join(' · ')}</span>
                )}
                <span>{EXCLUSION_TH[n.exclusion] ?? n.exclusion}</span>
              </p>
              {(n.verdict === 'consider' || n.verdict === 'ok_to_leave') && isMain(n.agreed_runs, review) && (
                <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  {n.verdict === 'consider' ? (
                    <>
                      <span className="chip chip-marker">ควรพิจารณา</span>
                      <Link to="/plo-synthesis" className="link text-xs">
                        ไปที่สังเคราะห์ PLO
                      </Link>
                    </>
                  ) : (
                    <span className="chip chip-neutral">ปล่อยไว้ได้</span>
                  )}
                  <AgreementChip agreed={n.agreed_runs} review={review} />
                </p>
              )}
              {n.reason_th && isMain(n.agreed_runs, review) && (
                <p className="mt-1.5 text-sm text-pencil">{n.reason_th}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** What some runs raised but too few agreed on: kept out of the main sections so
 *  one run's passing opinion is not read as a finding, but not hidden either. */
function BelowThreshold({ review }: { review: PLOSetReview }) {
  if (!isVoted(review)) return null
  const below = (agreed: number | undefined) => !isMain(agreed, review)
  const red = review.redundancies.filter((f) => below(f.agreed_runs))
  const ksec = review.ksec.filter((k) => !k.agrees && below(k.agreed_runs))
  const bloom = review.bloom.filter((b) => below(b.agreed_runs))
  const unused = review.unused_needs.filter((u) => u.verdict && below(u.agreed_runs))
  const total = red.length + ksec.length + bloom.length + unused.length
  if (total === 0) return null
  return (
    <details className="border-t border-hair pt-4">
      <summary className="eyebrow cursor-pointer">พบไม่ถึงเกณฑ์ ({total})</summary>
      <p className="mt-2 text-sm text-pencil">
        ข้อเหล่านี้มีบางรอบพูดถึงแต่ไม่ถึงเกณฑ์ {review.agreement_threshold ?? 1} รอบ — ยังไม่ควรถือเป็นข้อค้นพบ
      </p>
      <div className="mt-3 space-y-3">
        {red.length > 0 && (
          <div>
            <p className="text-sm font-medium text-graphite">{DROPPED_LABEL_TH.redundancy}</p>
            <ul className="mt-1 space-y-2">
              {red.map((g, i) => (
                <li key={i}>
                  <p className="data text-sm font-semibold text-graphite">
                    {g.plo_ids.join(' · ')}
                    <AgreementChip agreed={g.agreed_runs} review={review} />
                  </p>
                  <p className="mt-1 text-sm text-pencil">{g.reason_th}</p>
                </li>
              ))}
            </ul>
          </div>
        )}
        {ksec.length > 0 && (
          <div>
            <p className="text-sm font-medium text-graphite">{DROPPED_LABEL_TH.ksec}</p>
            <ul className="mt-1 space-y-2">
              {ksec.map((k) => (
                <li key={k.plo_id}>
                  <p className="text-sm">
                    <span className="data font-semibold text-graphite">{k.plo_id}</span>{' '}
                    <span className="data text-pencil">
                      {domains(k.current)} → {domains(k.suggested)}
                    </span>
                    <AgreementChip agreed={k.agreed_runs} review={review} />
                  </p>
                  <p className="mt-1 text-sm text-pencil">{k.reason_th}</p>
                </li>
              ))}
            </ul>
          </div>
        )}
        {bloom.length > 0 && (
          <div>
            <p className="text-sm font-medium text-graphite">{DROPPED_LABEL_TH.bloom}</p>
            <ul className="mt-1 space-y-2">
              {bloom.map((b) => (
                <li key={b.plo_id}>
                  <p className="text-sm">
                    <span className="data font-semibold text-graphite">{b.plo_id}</span>{' '}
                    <span className="data text-pencil">{bloomLabel(b.declared)}</span>
                    {b.suggested_level && b.suggested_level !== b.declared && (
                      <span className="data text-graphite"> → {bloomLabel(b.suggested_level)}</span>
                    )}
                    <AgreementChip agreed={b.agreed_runs} review={review} />
                  </p>
                  {b.reason_th && <p className="mt-1 text-sm text-pencil">{b.reason_th}</p>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {unused.length > 0 && (
          <div>
            <p className="text-sm font-medium text-graphite">{DROPPED_LABEL_TH.unused}</p>
            <ul className="mt-1 space-y-2">
              {unused.map((u) => (
                <li key={u.need_id}>
                  <p className="text-sm text-graphite">
                    {u.statement_th}
                    <span className="chip chip-neutral ml-2">
                      {u.verdict === 'consider' ? 'ควรพิจารณา' : 'ปล่อยไว้ได้'}
                    </span>
                    <AgreementChip agreed={u.agreed_runs} review={review} />
                  </p>
                  {u.reason_th && <p className="mt-1 text-sm text-pencil">{u.reason_th}</p>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  )
}
