import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import api from '../api/client'
import { JOB_PAGE } from '../api/jobs'
import { isCreatingIntake } from '../constants/intakeMode'
import { JobsProvider, useJobs } from '../hooks/useProgramJobs'
import { useProgram } from '../hooks/useProgram'
import { SESSION_STATUS_LABELS, STAGES, stageIndex, type StageDef } from '../constants/stages'

interface ProgramRow {
  program_id: string
  name_th: string
  field: string
  faculty: string
  current_stage: string | null
  session_status: string | null
}

type GateState = 'passed' | 'current' | 'ahead'

/** Where a stage sits relative to how far this program has reached.
 *
 * Reached-ness comes from the program's own `current_stage`, not from which
 * page happens to be open: a designer can open any stage at any time, and a nav
 * that marked whatever they clicked as "reached" would tell them nothing. */
function gateStateFor(stage: StageDef, reached: number): GateState {
  const here = STAGES.indexOf(stage)
  if (reached < 0) return here === 0 ? 'current' : 'ahead'
  if (here < reached) return 'passed'
  if (here === reached) return 'current'
  return 'ahead'
}

const GATE_TITLE: Record<GateState, string> = {
  passed: 'ผ่านแล้ว',
  current: 'อยู่ขั้นนี้',
  ahead: 'ยังไม่ถึง',
}

/** The gate on the rail, drawn as a mark from the มคอ.2 curriculum-mapping
 *  matrix: ● passed, ◐ the stage the program is at, ○ not reached. Told apart
 *  by fill, so the state survives greyscale printing and colour blindness. */
function GateMark({ state }: { state: GateState }) {
  return (
    <span className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center">
      <span className={`map-mark map-mark-${state}`} aria-hidden="true" />
      <span className="sr-only">{GATE_TITLE[state]}</span>
    </span>
  )
}

/** The legend the matrix itself carries, so the marks explain themselves. */
function GateLegend() {
  return (
    <ul className="hidden gap-3 px-6 text-[0.6875rem] text-pencil lg:flex" aria-hidden="true">
      {(['passed', 'current', 'ahead'] as const).map((state) => (
        <li key={state} className="flex items-center gap-1.5">
          <span className={`map-mark map-mark-${state} h-2.5 w-2.5`} />
          {GATE_TITLE[state]}
        </li>
      ))}
    </ul>
  )
}

/** Two engine stages, one review gate — drawn, because it is the one thing
 *  about this pipeline that surprises people. Without it, a designer hunts for
 *  a "Need" page that does not exist. */
function SharedGate({ stage }: { stage: StageDef }) {
  if (!stage.engineStages) return null
  return (
    <div className="mt-1 hidden pl-6 lg:block">
      <div className="ml-2 border-l border-dashed border-hair-strong pl-3">
        <ul className="space-y-0.5">
          {stage.engineStages.map((name) => (
            <li key={name} className="text-xs leading-snug text-pencil">
              {name}
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-1 ml-2 pl-3 text-[0.6875rem] leading-snug text-lead">{stage.gateNote}</p>
    </div>
  )
}

function StageRail({ reached }: { reached: number }) {
  return (
    <ol className="relative flex gap-1 overflow-x-auto px-3 [scrollbar-width:none] lg:block lg:space-y-1 lg:overflow-visible lg:px-3">
      {/* The rail itself: one continuous line every gate sits on. Hidden on
          small screens, where the stages scroll sideways and a vertical line
          would be a lie about the layout. */}
      <span
        className="absolute left-[1.5rem] top-4 bottom-4 hidden w-px bg-hair-strong lg:block"
        aria-hidden="true"
      />
      {STAGES.map((stage) => {
        const state = gateStateFor(stage, reached)
        return (
          <li key={stage.key} className="shrink-0 lg:shrink">
            <NavLink
              to={stage.route}
              className={({ isActive }) =>
                [
                  'group flex items-start gap-2 rounded-[3px] py-1.5 pr-2 transition-colors lg:gap-3',
                  isActive ? 'bg-sheet shadow-[0_0_0_1px_var(--color-hair)]' : 'hover:bg-sheet/60',
                ].join(' ')
              }
            >
              {({ isActive }) => (
                <>
                  <GateMark state={state} />
                  <span className="min-w-0">
                    <span className="flex items-baseline gap-2">
                      <span className="data text-[0.6875rem] text-lead">
                        {String(stage.ordinal).padStart(2, '0')}
                      </span>
                      <span
                        className={[
                          'truncate text-sm leading-snug lg:whitespace-normal',
                          isActive ? 'font-semibold' : '',
                          !isActive && state === 'ahead' ? 'text-pencil' : 'text-graphite',
                        ].join(' ')}
                      >
                        {stage.label}
                      </span>
                    </span>
                    {/* Only where the question is live. A designer learns these
                        five stages in a day, after which a summary under every
                        row is permanent noise competing with the gates. */}
                    {isActive && (
                      <span className="mt-0.5 hidden text-xs leading-snug text-pencil lg:block">
                        {stage.summary}
                      </span>
                    )}
                  </span>
                </>
              )}
            </NavLink>
            <SharedGate stage={stage} />
          </li>
        )
      })}
    </ol>
  )
}

function RailLink({ to, label, note }: { to: string; label: string; note: string }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        [
          'block rounded-[3px] px-3 py-1.5 text-sm text-graphite transition-colors',
          isActive
            ? 'bg-sheet font-semibold shadow-[0_0_0_1px_var(--color-hair)]'
            : 'hover:bg-sheet/60',
        ].join(' ')
      }
    >
      {label}
      <span className="mt-0.5 hidden text-xs font-normal leading-snug text-pencil lg:block">
        {note}
      </span>
    </NavLink>
  )
}

/** Which program every page on the right is reading and writing.
 *
 * The id lives in localStorage and each page picks it up silently, so without
 * this bar the answer to "which program am I editing?" is not on the screen. */
function ProgramBar({
  program,
  programId,
  creating,
}: {
  program: ProgramRow | null
  programId: string
  creating: boolean
}) {
  // Intake is typing a program that does not exist yet, so there is nothing here
  // to name — and naming the id still in storage said the designer was working
  // on the curriculum they had just navigated away from creating. The selected
  // one is still mentioned, in small type, because intake's "กลับไปแก้ไข" is the
  // way back to it and a bar that dropped it entirely would hide that.
  if (creating) {
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-hair bg-sheet px-4 py-3 sm:px-6 lg:px-10">
        <div className="min-w-0">
          <p className="eyebrow">กำลังสร้างหลักสูตรใหม่</p>
          <p className="font-display text-lg leading-tight text-pencil">ยังไม่บันทึก</p>
        </div>
        {programId && (
          <span className="ml-auto text-xs text-pencil">
            หลักสูตรที่เลือกไว้: <span className="data">{programId}</span>
          </span>
        )}
      </div>
    )
  }

  if (!programId) {
    return (
      <div className="border-b border-hair bg-sheet px-4 py-3 sm:px-6 lg:px-10">
        <p className="text-sm text-pencil">
          ยังไม่ได้เลือกหลักสูตร{' '}
          <NavLink to="/" className="link">
            เลือกจากรายการหลักสูตร
          </NavLink>
        </p>
      </div>
    )
  }

  const status = program?.session_status
  const awaiting = status === 'suspended'

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-hair bg-sheet px-4 py-3 sm:px-6 lg:px-10">
      <div className="min-w-0">
        {/* Labelled, because the name alone is just a string: a designer with
            two curricula open in two tabs cannot tell which one this is. */}
        <p className="eyebrow">หลักสูตรที่กำลังทำงาน</p>
        <div className="flex flex-wrap items-baseline gap-x-3">
          {/* Deliberately not an h1 — the page below owns that. This is chrome
              naming the working context, not the heading of the document. */}
          <p className="font-display text-lg leading-tight font-semibold text-graphite">
            {program?.name_th || program?.field || programId}
          </p>
          {program?.faculty && <span className="text-xs text-pencil">{program.faculty}</span>}
          <span className="data text-xs text-lead">{programId}</span>
        </div>
      </div>
      {status && (
        // A finished run is a person's approval and reads as a stamp; a run
        // waiting on the designer is the thing on the page to look at.
        <span
          className={[
            'ml-auto',
            status === 'completed'
              ? 'stamp'
              : status === 'rejected' || status === 'failed'
                ? 'stamp stamp-mandate'
                : awaiting
                  ? 'stamp stamp-pending'
                  : 'chip chip-neutral',
          ].join(' ')}
        >
          {SESSION_STATUS_LABELS[status] ?? status}
        </span>
      )}
    </div>
  )
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
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hair bg-stamp-wash px-4 py-2 text-sm text-stamp-deep sm:px-6 lg:px-10"
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
  const picking = pathname === '/'

  // Re-read on navigation: approving a checkpoint on one page moves the program
  // forward, and the rail has to show that without a reload. The shell degrades
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

  // The rail answers "how far has the program being worked on got", and while
  // one is being typed the answer is nowhere — not however far the curriculum
  // still sitting in storage happens to have reached.
  const reached = creating ? -1 : stageIndex(program?.current_stage ?? null)

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      {/* The rail sits on the paper, not on a dark slab: it is the margin of
          the document, closed off by a double rule like a ruled form's. */}
      <nav className="w-full shrink-0 border-b border-hair py-4 lg:sticky lg:top-0 lg:h-screen lg:w-[var(--rail-width)] lg:overflow-y-auto lg:border-b-0 lg:border-r-[3px] lg:border-double lg:border-r-hair-strong lg:py-7">
        <div className="px-4 pb-4 sm:px-6">
          <p className="eyebrow">OBE · มาตรฐาน อว.</p>
          <p className="font-display mt-0.5 text-xl leading-tight font-semibold text-graphite">
            ออกแบบหลักสูตร
          </p>
        </div>

        <StageRail reached={reached} />

        <div className="mt-3">
          <GateLegend />
        </div>

        <div className="mt-4 space-y-0.5 border-t border-hair px-3 pt-4">
          <RailLink to="/" label="หลักสูตรทั้งหมด" note="เลือกหลักสูตรที่จะทำงานด้วย" />
          <RailLink to="/pipeline" label="รันทั้งชุด" note="รันต่อเนื่องและอนุมัติทีละขั้น" />
        </div>
      </nav>

      {/* The provider wraps the whole column, so every page reads the same list
          and a job one page starts is still polled after the designer leaves it.
          It renders no element of its own. */}
      <JobsProvider programId={programId}>
        <div className="flex min-w-0 flex-1 flex-col">
          {!picking && <ProgramBar program={program} programId={programId} creating={creating} />}
          {/* Not on the program list or while a new program is being typed: in
              both the stored id is not the program on the screen, and a line
              about it would say a job is running on something not in view. */}
          {!picking && !creating && <RunningJobLine pathname={pathname} />}
          <main className="flex-1 px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
            <div className="mx-auto max-w-5xl">
              <Outlet />
            </div>
          </main>
        </div>
      </JobsProvider>
    </div>
  )
}
