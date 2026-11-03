import { useCallback, useEffect, useRef, useState } from 'react'
import api from '../../api/client'
import { JOB_PAGE, type JobKind } from '../../api/jobs'
import type { JobUsage, SessionUsage, SlotUsage, UsageSummary, UsageTotals } from '../../api/usage'
import { useReloadOnJobs } from '../../hooks/useReloadOnJobs'

/** Every kind: a job of any of them can have made model calls. */
const ALL_KINDS = Object.keys(JOB_PAGE) as JobKind[]

const SHOWN_RUNS = 5

const LATENCY_HINT =
  'รวมเวลาของทุกการเรียกโมเดล — การเรียกพร้อมกันทำให้ตัวเลขนี้มากกว่าเวลาที่รอจริง'

const num = (n: number): string => n.toLocaleString('en-US')
const seconds = (ms: number): string => `${(ms / 1000).toFixed(1)} วินาที`

const ZERO: UsageTotals = {
  calls: 0,
  failed_calls: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  reasoning_tokens: 0,
  latency_ms: 0,
}

const plus = (a: UsageTotals, b: UsageTotals): UsageTotals => ({
  calls: a.calls + b.calls,
  failed_calls: a.failed_calls + b.failed_calls,
  prompt_tokens: a.prompt_tokens + b.prompt_tokens,
  completion_tokens: a.completion_tokens + b.completion_tokens,
  reasoning_tokens: a.reasoning_tokens + b.reasoning_tokens,
  latency_ms: a.latency_ms + b.latency_ms,
})

const minus = (a: UsageTotals, b: UsageTotals): UsageTotals => ({
  calls: a.calls - b.calls,
  failed_calls: a.failed_calls - b.failed_calls,
  prompt_tokens: a.prompt_tokens - b.prompt_tokens,
  completion_tokens: a.completion_tokens - b.completion_tokens,
  reasoning_tokens: a.reasoning_tokens - b.reasoning_tokens,
  latency_ms: a.latency_ms - b.latency_ms,
})

function TotalsLine({ t }: { t: UsageTotals }) {
  return (
    <span className="data text-xs text-lead">
      เรียก {num(t.calls)} ครั้ง · ไม่ผ่าน {num(t.failed_calls)} · token เข้า {num(t.prompt_tokens)} /
      ออก {num(t.completion_tokens)} / คิด {num(t.reasoning_tokens)} ·{' '}
      <span title={LATENCY_HINT}>เวลาเรียกรวม {seconds(t.latency_ms)}</span>
    </span>
  )
}

/** One run of the pipeline: a job, or a whole-pipeline session. */
interface Run {
  key: string
  title: string
  started: string
  total: UsageTotals
  by_slot: SlotUsage[]
}

const fromJob = (j: JobUsage): Run => ({
  key: `job:${j.job_id}`,
  title: j.label_th || j.kind || 'งานที่ไม่พบแล้ว',
  started: j.started,
  total: j.total,
  by_slot: j.by_slot,
})

const fromSession = (x: SessionUsage): Run => ({
  key: `session:${x.session_id}`,
  title: 'รันทั้งชุด',
  started: x.started,
  total: x.total,
  by_slot: x.by_slot,
})

function RunBlock({ run }: { run: Run }) {
  return (
    <li className="border-t border-hair py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="text-sm font-semibold text-graphite">{run.title}</span>
        <span className="data text-xs text-pencil">
          {new Date(run.started).toLocaleString('th-TH')}
        </span>
      </div>
      <div className="mt-0.5">
        <TotalsLine t={run.total} />
      </div>
      <ul className="mt-1.5 space-y-0.5 pl-3">
        {run.by_slot.map((s) => (
          <li key={s.slot} className="flex flex-wrap gap-x-3">
            <span className="data w-36 text-xs text-graphite">{s.slot}</span>
            <TotalsLine t={s} />
          </li>
        ))}
      </ul>
    </li>
  )
}

/** What the model calls cost, for the program: one total line, then each job and
 *  whole-pipeline session (newest first) with its per-slot split, then whatever the
 *  total holds beyond them (calls made by scripts). A failed read hides the panel —
 *  it is an aside to the run history, never a reason to break the page.
 *
 *  `refreshKey` changes when the page learns a run moved (a session changed status);
 *  the panel reloads then, and on its own when a job ends. */
export default function UsagePanel({
  programId,
  refreshKey = '',
}: {
  programId: string
  refreshKey?: string
}) {
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [showAll, setShowAll] = useState(false)

  // Bumped by every load and every program change; a response that is not the
  // latest request is dropped, so a slow older read cannot overwrite a newer one
  // and a response for the previous program cannot land on this one.
  const latest = useRef(0)

  // A new program starts empty: the old one's figures must not stay on screen
  // while the new read is in flight, nor its "show all" choice carry over.
  useEffect(() => {
    latest.current += 1
    setUsage(null)
    setShowAll(false)
  }, [programId])

  const load = useCallback(async () => {
    if (!programId) {
      setUsage(null)
      return
    }
    const mine = ++latest.current
    try {
      const res = await api.get<UsageSummary>(`/programs/${programId}/usage`)
      if (latest.current === mine) setUsage(res.data)
    } catch {
      if (latest.current === mine) setUsage(null)
    }
  }, [programId])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  useReloadOnJobs(ALL_KINDS, () => void load())

  if (!usage || usage.total.calls === 0) return null

  const runs: Run[] = [
    ...usage.by_job.map(fromJob),
    ...(usage.by_session ?? []).map(fromSession),
  ].sort((a, b) => b.started.localeCompare(a.started))
  const shown = showAll ? runs : runs.slice(0, SHOWN_RUNS)
  const hidden = runs.length - SHOWN_RUNS
  const accounted = runs.reduce<UsageTotals>((acc, r) => plus(acc, r.total), ZERO)
  const other = minus(usage.total, accounted)

  return (
    <section className="panel mb-4 p-4" aria-label="การใช้โมเดล">
      <h2 className="text-sm font-semibold text-graphite">การใช้โมเดล</h2>
      <div className="mt-1">
        <TotalsLine t={usage.total} />
      </div>
      {shown.length > 0 && (
        <ul className="mt-2">
          {shown.map((r) => (
            <RunBlock key={r.key} run={r} />
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
      {other.calls > 0 && (
        <div className="mt-2 border-t border-hair pt-2.5">
          <span className="text-sm font-semibold text-graphite">อื่น ๆ (สคริปต์)</span>
          <div className="mt-0.5">
            <TotalsLine t={other} />
          </div>
        </div>
      )}
    </section>
  )
}
