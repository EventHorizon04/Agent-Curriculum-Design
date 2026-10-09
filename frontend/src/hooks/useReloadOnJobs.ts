import { useCallback, useLayoutEffect, useMemo, useRef } from 'react'
import type { JobInfo, JobKind } from '../api/jobs'
import { useJobs } from './useProgramJobs'

/**
 * Run `reload` once for every job of one of `kinds` that this page watched
 * running and later sees reach a terminal status: `succeeded` or `failed`.
 *
 * Failed counts: a run that fails part-way has already changed rows. `/needs/run`
 * commits the new skills before need_combination can time out, run out of quota
 * or come back empty, so a page that reloaded only on success would keep showing
 * the skills the run had already replaced.
 *
 * What is watched is a job this page started (hand it to the returned `watch`)
 * or one the shared list showed running while the page was mounted. Nothing is
 * compared against a clock, since the server's and the browser's may disagree,
 * and a job that finished before the page mounted is covered by the page's own
 * load on mount. `reload` gets the finished job, so a page can choose how loudly
 * to reload from its kind. The set is forgotten when the program changes:
 * another program's jobs are not this one's to reload for.
 *
 * The effects are keyed on strings, not on the job objects, which get a new
 * identity on every poll and would reload every two seconds. They are layout
 * effects, not passive ones: when the result arrives the run screen is replaced
 * in the same commit, and a passive effect would let the browser paint the
 * previous data (or an empty state with a live start button) for a moment before
 * the reload put the loading line up. Pass the same `kinds` array every render (a
 * module constant); `reload` may be any function, the latest one is called.
 */
export function useReloadOnJobs(
  kinds: JobKind[],
  reload: (job: JobInfo) => void,
): (job: JobInfo) => void {
  const { programId, jobs } = useJobs()
  const watching = useRef(new Set<string>())
  const kindsKey = kinds.join(',')

  const ofKinds = useMemo(() => {
    const wanted = kindsKey.split(',')
    return jobs.filter((j) => wanted.includes(j.kind))
  }, [jobs, kindsKey])
  const runningKey = ofKinds
    .filter((j) => j.status === 'running')
    .map((j) => j.job_id)
    .join(',')
  const settledKey = ofKinds
    .filter((j) => j.status !== 'running')
    .map((j) => `${j.job_id}:${j.status}`)
    .join(',')

  // What the keyed effects read when they fire. Assigned first, so it is current.
  const latest = useRef({ ofKinds, reload })
  useLayoutEffect(() => {
    latest.current = { ofKinds, reload }
  })

  useLayoutEffect(() => {
    watching.current.clear()
  }, [programId])
  useLayoutEffect(() => {
    for (const job of latest.current.ofKinds) {
      if (job.status === 'running') watching.current.add(job.job_id)
    }
  }, [runningKey, programId])
  useLayoutEffect(() => {
    // Forgotten as soon as it has ended, whichever way, so it fires once.
    for (const job of latest.current.ofKinds) {
      if (job.status !== 'running' && watching.current.delete(job.job_id)) {
        latest.current.reload(job)
      }
    }
  }, [settledKey, programId])

  return useCallback((job: JobInfo): void => {
    watching.current.add(job.job_id)
  }, [])
}
