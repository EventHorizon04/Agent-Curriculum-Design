import api from './client'

/** The seven stage runs the backend carries out in the background
 *  (src/curriculum_agent/api/jobs.py). Spelled exactly as the API does. */
export type JobKind =
  | 'needs_pipeline'
  | 'skill_extraction'
  | 'need_combination'
  | 'plo_synthesis'
  | 'plo_review'
  | 'plo_report'
  | 'plo_revalidate'

export type JobStatus = 'running' | 'succeeded' | 'failed'

/** JobInfo. `result` is exactly the body the route answered before it became a
 *  job — its shape depends on `kind`, so it is `unknown` until a page that
 *  knows its kind narrows it. Timestamps are ISO strings with an explicit
 *  `+00:00`, so `Date.parse` reads them as the instants they are. */
export interface JobInfo {
  job_id: string
  program_id: string
  kind: JobKind
  label_th: string
  status: JobStatus
  params: Record<string, unknown>
  result: unknown
  error_th: string | null
  created_at: string
  finished_at: string | null
}

/** Which page owns each kind of job: where the designer goes to see its outcome.
 *  Skill extraction and need combination share one page because they share one
 *  review gate; the SMART revalidation is a button on the synthesis page. */
export const JOB_PAGE: Record<JobKind, { path: string }> = {
  needs_pipeline: { path: '/skill-extraction' },
  skill_extraction: { path: '/skill-extraction' },
  need_combination: { path: '/skill-extraction' },
  plo_synthesis: { path: '/plo-synthesis' },
  plo_revalidate: { path: '/plo-synthesis' },
  plo_review: { path: '/plo-review' },
  plo_report: { path: '/plo-report' },
}

/** Start a stage run. The route answers 202 with the job it has just recorded,
 *  not with the stage's output — that arrives later, as the job's `result`.
 *  Refusals (404/422/503, and 409 while the program already has a writer) throw
 *  as axios errors, like any other call. */
export async function startJob(path: string, body?: unknown): Promise<JobInfo> {
  const res = await api.post<JobInfo>(path, body)
  return res.data
}

/** The program's most recent jobs, newest first (the API caps it at 20). */
export async function listJobs(programId: string): Promise<JobInfo[]> {
  const res = await api.get<JobInfo[]>(`/programs/${programId}/jobs/`)
  return res.data
}
