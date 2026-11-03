import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import api from '../../api/client'
import { JOB_PAGE, type JobKind } from '../../api/jobs'
import type { JobUsage, UsageSummary, UsageTotals } from '../../api/usage'
import { useReloadOnJobs } from '../../hooks/useReloadOnJobs'

/** Every kind: a job of any of them can have made model calls. */
const ALL_KINDS = Object.keys(JOB_PAGE) as JobKind[]

const SHOWN_JOBS = 5

const num = (n: number): string => n.toLocaleString('en-US')
const seconds = (ms: number): string => `${(ms / 1000).toFixed(1)} วินาที`

function TotalsLine({ t }: { t: UsageTotals }) {
  return (
    <span className="data text-xs text-lead">
      เรียก {num(t.calls)} ครั้ง · ไม่ผ่าน {num(t.failed_calls)} · token เข้า {num(t.prompt_tokens)} /
      ออก {num(t.completion_tokens)} / คิด {num(t.reasoning_tokens)} · เวลา {seconds(t.latency_ms)}
    </span>
  )
}

function JobBlock({ job }: { job: JobUsage }) {
  return (
    <li className="border-t border-hair py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="text-sm font-semibold text-graphite">
          {job.label_th || job.kind || 'งานที่ไม่พบแล้ว'}
        </span>
        <span className="data text-xs text-pencil">
          {new Date(job.started).toLocaleString('th-TH')}
        </span>
      </div>
      <div className="mt-0.5">
        <TotalsLine t={job.total} />
      </div>
      <ul className="mt-1.5 space-y-0.5 pl-3">
        {job.by_slot.map((s) => (
          <li key={s.slot} className="flex flex-wrap gap-x-3">
            <span className="data w-36 text-xs text-graphite">{s.slot}</span>
            <TotalsLine t={s} />
          </li>
        ))}
      </ul>
    </li>
  )
}

/** What the model calls cost, for the program: one total line, then each job
 *  (newest first) with its per-slot split. A failed read hides the panel — it
 *  is an aside to the run history, never a reason to break the page. */
export default function UsagePanel({ programId }: { programId: string }) {
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [showAll, setShowAll] = useState(false)

  // The program the page is on now; a response for any other is dropped.
  const currentId = useRef(programId)
  useLayoutEffect(() => {
    currentId.current = programId
  }, [programId])

  const load = useCallback(async () => {
    if (!programId) {
      setUsage(null)
      return
    }
    try {
      const res = await api.get<UsageSummary>(`/programs/${programId}/usage`)
      if (currentId.current === programId) setUsage(res.data)
    } catch {
      if (currentId.current === programId) setUsage(null)
    }
  }, [programId])

  useEffect(() => {
    void load()
  }, [load])

  useReloadOnJobs(ALL_KINDS, () => void load())

  if (!usage || usage.total.calls === 0) return null

  const jobs = showAll ? usage.by_job : usage.by_job.slice(0, SHOWN_JOBS)
  const hidden = usage.by_job.length - SHOWN_JOBS

  return (
    <section className="panel mb-4 p-4" aria-label="การใช้โมเดล">
      <h2 className="text-sm font-semibold text-graphite">การใช้โมเดล</h2>
      <div className="mt-1">
        <TotalsLine t={usage.total} />
      </div>
      {jobs.length > 0 && (
        <ul className="mt-2">
          {jobs.map((j) => (
            <JobBlock key={j.job_id} job={j} />
          ))}
        </ul>
      )}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="btn btn-sm btn-secondary mt-2"
        >
          {showAll ? 'ซ่อนงานเก่า' : `แสดงอีก ${hidden} งาน`}
        </button>
      )}
    </section>
  )
}
