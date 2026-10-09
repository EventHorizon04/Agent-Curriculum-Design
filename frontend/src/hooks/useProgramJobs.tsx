import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useLocation } from 'react-router-dom'
import { listJobs, type JobInfo, type JobKind } from '../api/jobs'

/** How often a program with a running job is asked how it is getting on. */
const POLL_MS = 2000

export interface JobsValue {
  /** The program these jobs belong to. */
  programId: string
  /** Every job the last read returned, newest first. Its identity changes on
   *  every poll: derive primitives from it before keying an effect on it. */
  jobs: JobInfo[]
  /** The newest job still running, if any. A program has at most one. */
  running: JobInfo | null
  /** The newest job (by `created_at`) whose kind is one of `kinds`, whatever
   *  its status — so a run that finished while the browser was closed reads the
   *  same as one watched to the end. */
  latestOf: (kinds: JobKind[]) => JobInfo | null
  /** Re-read the list now. Never throws. */
  refresh: () => Promise<void>
  /** Tell the hook a job has just been started by this page, so it shows at
   *  once and polling begins without waiting for the next read. */
  started: (job: JobInfo) => void
}

const JobsContext = createContext<JobsValue | null>(null)

/** The jobs as one program's list last reported them. The program id travels
 *  with the rows so a list is only ever shown for the program it belongs to.
 *  `failed` is true while the most recent read of it did not answer. */
interface Store {
  programId: string
  jobs: JobInfo[]
  failed: boolean
}

const NO_JOBS: JobInfo[] = []

/** Earlier in the list wins a tie: the API sends newest first. */
function newest(jobs: JobInfo[]): JobInfo | null {
  let best: JobInfo | null = null
  for (const job of jobs) {
    if (best === null || Date.parse(job.created_at) > Date.parse(best.created_at)) best = job
  }
  return best
}

/**
 * The jobs of one program, read from the server and kept fresh while one runs.
 *
 * State is derived from the server's list, never from transitions this page
 * happened to witness: on mount (and when the program changes) the list is
 * fetched, and while any job is `running` it is fetched again every
 * {@link POLL_MS}. A failed read keeps the last list and tries again on the next
 * tick — including a first read that failed, since with no list there is nothing
 * to say a job is running and polling would otherwise never begin. It is also
 * read again when the route changes and when the tab becomes visible, because a
 * job another tab or client started is otherwise unknown until a page here
 * starts one of its own.
 */
function useProgramJobs(programId: string): JobsValue {
  const [store, setStore] = useState<Store>({ programId: '', jobs: NO_JOBS, failed: false })
  // Derived rather than reset in an effect: on the render where the program
  // changes, the old program's jobs are already gone, so there is no frame in
  // which program A's running job is shown on program B.
  const here = store.programId === programId
  const jobs = here ? store.jobs : NO_JOBS
  const failed = here && store.failed

  // A request token. Every read takes the next one and applies its answer only
  // if it is still the newest, which drops (a) an answer for a program the
  // designer has since left, (b) an older read overtaken by a newer one, and
  // (c) a read issued before `started` recorded a job, which would otherwise
  // overwrite the list with one that does not contain it yet.
  const latest = useRef(0)
  const warned = useRef(false)
  // The program on screen *now*. `refresh` and `started` are handed to pages and
  // called later (after an await, from a handler), so a copy that closed over the
  // program of the render it was made in would, after a switch, write that
  // program's list over the new one's. They read this instead. Set in a layout
  // effect, not during render, which runs before any passive effect or event that
  // could reach them.
  const current = useRef(programId)
  useLayoutEffect(() => {
    current.current = programId
  }, [programId])

  /** Make every read still in flight stale. */
  const supersede = useCallback((): void => {
    latest.current++
  }, [])

  const load = useCallback(async (pid: string): Promise<void> => {
    const token = ++latest.current
    try {
      const rows = await listJobs(pid)
      // The program check is belt and braces: leaving a program already
      // supersedes its reads, but a read must never be the thing that decides.
      if (token !== latest.current || pid !== current.current) return
      warned.current = false
      setStore({ programId: pid, jobs: rows, failed: false })
    } catch (err) {
      if (token !== latest.current || pid !== current.current) return
      // The last list stays. Once per outage: the next tick retries, and a
      // line every two seconds would bury whatever else is in the console.
      if (!warned.current) {
        warned.current = true
        console.warn('[jobs] could not read the job list; keeping the last one and retrying', err)
      }
      setStore((prev) =>
        prev.programId === pid ? { ...prev, failed: true } : { programId: pid, jobs: NO_JOBS, failed: true },
      )
    }
  }, [])

  useEffect(() => {
    if (!programId) return
    void load(programId)
    // Leaving this program (or unmounting) orphans any read still in flight.
    return supersede
  }, [programId, load, supersede])

  const needsPolling = failed || jobs.some((j) => j.status === 'running')

  useEffect(() => {
    if (!programId || !needsPolling) return
    let cancelled = false
    let timer = 0
    // setTimeout rather than setInterval: the next read is scheduled only after
    // the last one has answered, so a slow endpoint never stacks requests.
    const tick = async (): Promise<void> => {
      await load(programId)
      if (!cancelled) timer = window.setTimeout(tick, POLL_MS)
    }
    timer = window.setTimeout(tick, POLL_MS)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [programId, needsPolling, load])

  const refresh = useCallback(async (): Promise<void> => {
    if (current.current) await load(current.current)
  }, [load])

  // The route changed: a page was opened, and whatever another tab or client
  // started since the last read is news to this one. Skipped on mount, where the
  // read above is already under way.
  const { pathname } = useLocation()
  const seenPath = useRef(pathname)
  useEffect(() => {
    if (seenPath.current === pathname) return
    seenPath.current = pathname
    void refresh()
  }, [pathname, refresh])

  // Timers are throttled in a background tab, so a tab coming back to the front
  // may be minutes behind: read at once instead of waiting out the next tick.
  useEffect(() => {
    const onVisible = (): void => {
      if (document.visibilityState === 'visible') void refresh()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refresh])

  const started = useCallback(
    (job: JobInfo): void => {
      const pid = current.current
      // A job for a program the designer has already switched away from is not
      // this view's to show.
      if (job.program_id !== pid) return
      supersede()
      setStore((prev) => ({
        programId: pid,
        jobs: [
          job,
          ...(prev.programId === pid ? prev.jobs : NO_JOBS).filter((j) => j.job_id !== job.job_id),
        ],
        failed: prev.programId === pid && prev.failed,
      }))
    },
    [supersede],
  )

  const latestOf = useCallback(
    (kinds: JobKind[]): JobInfo | null => newest(jobs.filter((j) => kinds.includes(j.kind))),
    [jobs],
  )

  const running = useMemo(() => newest(jobs.filter((j) => j.status === 'running')), [jobs])

  return useMemo(
    () => ({ programId, jobs, running, latestOf, refresh, started }),
    [programId, jobs, running, latestOf, refresh, started],
  )
}

/** One view of the program's jobs, shared by every page under it. Mounted by
 *  StageLayout, which stays mounted across navigation, so a job started on one
 *  page is still known — and still polled — when the designer opens another. */
export function JobsProvider({ programId, children }: { programId: string; children: ReactNode }) {
  const value = useProgramJobs(programId)
  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>
}

// The one hook this file exports beside its component: they are a pair, and the
// provider's state hook is deliberately not exported for anyone else to call.
// eslint-disable-next-line react-refresh/only-export-components
export function useJobs(): JobsValue {
  const value = useContext(JobsContext)
  if (value === null) {
    throw new Error('useJobs must be used inside <JobsProvider> (StageLayout mounts it)')
  }
  return value
}
