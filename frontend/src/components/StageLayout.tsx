import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import api from '../api/client'
import { JOB_PAGE } from '../api/jobs'
import { isCreatingIntake } from '../constants/intakeMode'
import { JobsProvider, useJobs } from '../hooks/useProgramJobs'
import { useProgram } from '../hooks/useProgram'
import { stageIndex, stagesFor, type AgentMode } from '../constants/stages'
import StageBar from './StageBar'
import TopBar from './TopBar'

export interface ProgramRow {
  program_id: string
  name_th: string
  field: string
  faculty: string
  current_stage: string | null
  session_status: string | null
  agent_mode?: AgentMode
}

/** The time a job started, in the viewer's own clock — `created_at` carries an
 *  explicit offset, so it is the instant the run began wherever it is read. */
function startedAt(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  return at.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })
}

/** One line, on every page, while the program has a job running.
 *
 * A run outlives the page that started it — the designer can move to another
 * stage, or reload — so without this the only sign that a program is busy is a
 * 409 from the next thing they try. The dial is the same mark the run screen
 * uses, so "something is being filled in" reads the same in both places. */
function RunningJobLine({ pathname }: { pathname: string }) {
  const { running } = useJobs()
  if (!running) return null

  const owner = JOB_PAGE[running.kind]?.path
  const start = startedAt(running.created_at)
  return (
    <div className="mx-auto mt-4 w-full max-w-5xl px-4 sm:px-6 lg:px-10">
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl bg-stamp-wash px-4 py-3 text-sm text-stamp-deep"
    >
      <span className="run-dial" aria-hidden="true" />
      <span>
        กำลังทำงาน: {running.label_th || running.kind}
        {start && ` · เริ่ม ${start}`}
      </span>
      {owner && owner !== pathname && (
        <Link to={owner} className="link ml-auto">
          ไปที่หน้างานนี้
        </Link>
      )}
    </div>
    </div>
  )
}

export default function StageLayout() {
  const { programId } = useProgram()
  const [program, setProgram] = useState<ProgramRow | null>(null)
  const { pathname, state } = useLocation()
  // Guarded by the path as well as the flag: location state rides along with a
  // history entry, and only intake means anything by this one.
  const creating = pathname === '/intake' && isCreatingIntake(state)
  // The program list is where a curriculum is chosen, not worked on. A bar
  // reading "หลักสูตรที่กำลังทำงาน" above a table of every program says the
  // designer is inside one while they are standing outside all of them — and it
  // is the one page that shows which is selected on its own row.
  const bare = pathname === '/' || pathname === '/my-programs'

  // Re-read on navigation: approving a checkpoint on one page moves the program
  // forward, and the stage bar has to show that without a reload. The shell degrades
  // to bare navigation if the API is unreachable — it must never be the reason
  // a page fails to render.
  useEffect(() => {
    if (!programId) {
      setProgram(null)
      return
    }
    let cancelled = false
    api
      .get<ProgramRow[]>('/programs/')
      .then((res) => {
        if (!cancelled) {
          setProgram(res.data.find((p) => p.program_id === programId) ?? null)
        }
      })
      .catch(() => {
        if (!cancelled) setProgram(null)
      })
    return () => {
      cancelled = true
    }
  }, [programId, pathname])

  // The stage bar answers "how far has the program being worked on got", and while
  // one is being typed the answer is nowhere — not however far the curriculum
  // still sitting in storage happens to have reached.
  const stages = stagesFor(program?.agent_mode ?? 'multi')
  const reached = creating ? -1 : stageIndex(program?.current_stage ?? null, stages)

  const showPipeline = !bare && !creating && program?.agent_mode !== 'single' && !!programId

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar showPipeline={showPipeline} showCreate={bare} />
      {/* The provider wraps everything below the bar, so every page reads the
          same list and a job one page starts is still polled after the designer
          leaves it. It renders no element of its own. */}
      <JobsProvider programId={programId}>
        {!bare && (
          <StageBar
            program={program}
            programId={programId}
            creating={creating}
            stages={stages}
            reached={reached}
            pathname={pathname}
          />
        )}
        {/* Not on the program list or while a new program is being typed: in
            both the stored id is not the program on the screen, and a line
            about it would say a job is running on something not in view. */}
        {!bare && !creating && <RunningJobLine pathname={pathname} />}
        {pathname === '/' ? (
          <main className="flex-1">
            <Outlet />
          </main>
        ) : (
          <main className="flex-1 px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
            <div className="mx-auto max-w-5xl">
              <Outlet />
            </div>
          </main>
        )}
      </JobsProvider>
    </div>
  )
}
