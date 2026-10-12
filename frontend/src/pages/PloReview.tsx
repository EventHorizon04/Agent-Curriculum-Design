import { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useProgram } from '../hooks/useProgram'
import { useJobs } from '../hooks/useProgramJobs'
import { useReloadOnJobs } from '../hooks/useReloadOnJobs'
import RunProgress, { LoadingLine, RunFailure } from '../components/RunProgress'
import { PLO_REVIEW_PLAN } from '../constants/runPlans'
import api from '../api/client'
import { startJob, type JobKind } from '../api/jobs'
import { BLOOM_ORDER, bloomLabel } from '../constants/bloom'
import { ksecLabel, stakeholderLabel } from '../constants/stakeholder'
import type {
  KsecFinding,
  PLOReviewResponse,
  PLOSetReview,
  UnusedNeedFinding,
} from '../types/ploReview'

/** The job kinds whose runs this page shows. */
const PAGE_KINDS: JobKind[] = ['plo_review']
/** The jobs that change what this page draws, whichever page started them: the
 *  review is a reading of the PLOs and the Needs, so a synthesis, a re-check, a
 *  new report or a new set of Needs all leave it describing a set that moved. */
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
  const [starting, setStarting] = useState(false)
  const [runError, setRunError] = useState<RunError | null>(null)

  const { running, latestOf, started, refresh } = useJobs()
  // `running` is any job of this program; `mine` is the review this page shows.
  const mine = running?.kind === 'plo_review' ? running : null
  const last = latestOf(PAGE_KINDS)
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
      const res = await api.get<PLOReviewResponse>(`/programs/${programId}/plos/review`)
      if (mineRead === latestRead.current) setRead({ programId, response: res.data })
    } catch {
      if (mineRead === latestRead.current) {
        setLoadError('โหลดผลตรวจไม่สำเร็จ ตรวจว่า API ทำงานอยู่ แล้วลองใหม่')
      }
    }
  }, [programId])

  const watch = useReloadOnJobs(RELOAD_KINDS, () => void fetchData())

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
  const agentOff = data?.review_enabled === false

  return (
    <div className="space-y-6">
      <header>
        <p className="eyebrow">ขั้นที่ 6</p>
        <h1 className="page-title">ตรวจคุณภาพชุด PLO</h1>
        <p className="mt-1 text-sm text-pencil">
          QA agent อ่าน PLO ทั้งชุดที่ทำเสร็จแล้ว แล้วให้คำแนะนำ — ไม่ได้แก้ PLO ให้
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

      {mine ? (
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
            <p className="notice notice-warn">
              ผลนี้ตรวจจาก PLO ชุดก่อน — PLO หรือ Need เปลี่ยนหลังการตรวจ กดตรวจใหม่ให้ตรงกับชุดปัจจุบัน
            </p>
          )}

          {review.summary_th && <p className="record text-base">{review.summary_th}</p>}

          <Overview review={review} />
          <Redundancies review={review} />
          <KsecSection rows={review.ksec} />
          <BloomSection review={review} />
          <UnusedNeeds needs={review.unused_needs} />

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

/** Who made the review, and when. A code-only review says so and why: it is the
 *  same page with fewer opinions on it, and the designer should not mistake the
 *  missing ones for a clean bill of health. */
function StatusLine({ review }: { review: PLOSetReview }) {
  const when = formatCreatedAt(review.created_at)
  if (review.reviewed_by === 'agent') {
    return (
      <p className="text-sm text-pencil">
        ตรวจโดย agent · {review.model} · {when}
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
  const groups = review.redundancies
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
                <p className="data text-sm font-semibold text-graphite">{g.plo_ids.join(' · ')}</p>
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

function KsecTable({ rows }: { rows: KsecFinding[] }) {
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
              </td>
              <td className="align-top text-pencil">{r.reason_th}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function KsecSection({ rows }: { rows: KsecFinding[] }) {
  // The ones that disagree are what the designer came for; the rest are proof
  // the check ran, so they sit behind a fold.
  const differing = rows.filter((r) => !r.agrees)
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
          {differing.length > 0 && <KsecTable rows={differing} />}
          {agreeing.length > 0 && (
            <details>
              <summary className="cursor-pointer text-sm text-pencil">
                ตรงกับหมวดเดิม {agreeing.length} ข้อ
              </summary>
              <div className="mt-2">
                <KsecTable rows={agreeing} />
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  )
}

function BloomSection({ review }: { review: PLOSetReview }) {
  const rows = review.bloom
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
              </p>
              {b.reason_th && <p className="mt-1 text-sm text-pencil">{b.reason_th}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function UnusedNeeds({ needs }: { needs: UnusedNeedFinding[] }) {
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
                <span>{ksecLabel(n.ksec_category)}</span>
                {n.stakeholder_types.length > 0 && (
                  <span>{n.stakeholder_types.map(stakeholderLabel).join(' · ')}</span>
                )}
                <span>{EXCLUSION_TH[n.exclusion] ?? n.exclusion}</span>
              </p>
              {(n.verdict === 'consider' || n.verdict === 'ok_to_leave') && (
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
                </p>
              )}
              {n.reason_th && <p className="mt-1.5 text-sm text-pencil">{n.reason_th}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
