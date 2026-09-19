import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import api from '../api/client'
import { isCreatingIntake } from '../constants/intakeMode'
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

/** The gate on the rail. Three states, told apart by fill rather than by colour
 *  — colour in this interface means "mandate", and a gate is not one. */
function GateMark({ state }: { state: GateState }) {
  const base = 'block h-2.5 w-2.5 rotate-45 transition-colors'
  const skin =
    state === 'current'
      ? 'bg-field'
      : state === 'passed'
        ? 'border border-field/70'
        : 'border border-dashed border-field/25'
  return (
    <span className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center">
      <span className={`${base} ${skin}`} aria-hidden="true" />
      <span className="sr-only">{GATE_TITLE[state]}</span>
    </span>
  )
}

/** Two engine stages, one review gate — drawn, because it is the one thing
 *  about this pipeline that surprises people. Without it, a designer hunts for
 *  a "Need" page that does not exist. */
function SharedGate({ stage }: { stage: StageDef }) {
  if (!stage.engineStages) return null
  return (
    <div className="mt-1 hidden pl-6 lg:block">
      <div className="relative border-l border-ink-line pl-3">
        <span
          className="absolute -left-[3px] top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-field/60"
          aria-hidden="true"
        />
        <ul className="space-y-0.5">
          {stage.engineStages.map((name) => (
            <li key={name} className="text-xs leading-snug text-field/45">
              {name}
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-1.5 pl-3 text-xs leading-snug text-field/35">{stage.gateNote}</p>
    </div>
  )
}

function StageRail({ reached }: { reached: number }) {
  return (
    <ol className="relative flex gap-1 overflow-x-auto px-3 lg:block lg:space-y-1 lg:overflow-visible lg:px-3">
      {/* The rail itself: one continuous line every gate sits on. Hidden on
          small screens, where the stages scroll sideways and a vertical line
          would be a lie about the layout. */}
      <span
        className="absolute left-[1.5rem] top-3 bottom-3 hidden w-px bg-ink-line lg:block"
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
                  'group flex items-start gap-2 rounded-sm py-1.5 pr-2 transition-colors lg:gap-3',
                  isActive ? 'bg-ink-raised' : 'hover:bg-ink-raised/60',
                ].join(' ')
              }
            >
              {({ isActive }) => (
                <>
                  <GateMark state={state} />
                  <span className="min-w-0">
                    <span className="flex items-baseline gap-2">
                      <span className="data text-[0.6875rem] text-field/40">
                        {String(stage.ordinal).padStart(2, '0')}
                      </span>
                      <span
                        className={[
                          'truncate text-sm leading-snug lg:whitespace-normal',
                          state === 'ahead' ? 'text-field/55' : 'text-field/90',
                        ].join(' ')}
                      >
                        {stage.label}
                      </span>
                    </span>
                    {/* Only where the question is live. A designer learns these
                        five stages in a day, after which a summary under every
                        row is permanent noise competing with the gates. */}
                    {isActive && (
                      <span className="mt-0.5 hidden text-xs leading-snug text-field/45 lg:block">
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
          'block rounded-sm px-3 py-1.5 text-sm transition-colors',
          isActive ? 'bg-ink-raised text-field' : 'text-field/70 hover:bg-ink-raised/60',
        ].join(' ')
      }
    >
      {label}
      <span className="mt-0.5 hidden text-xs leading-snug text-field/45 lg:block">{note}</span>
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
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-rule bg-card px-6 py-3 lg:px-10">
        <div className="min-w-0">
          <p className="eyebrow">กำลังสร้างหลักสูตรใหม่</p>
          <p className="font-record text-lg leading-tight text-mute">ยังไม่บันทึก</p>
        </div>
        {programId && (
          <span className="ml-auto text-xs text-faint">
            หลักสูตรที่เลือกไว้: <span className="data">{programId}</span>
          </span>
        )}
      </div>
    )
  }

  if (!programId) {
    return (
      <div className="border-b border-rule bg-card px-6 py-3 lg:px-10">
        <p className="text-sm text-mute">
          ยังไม่ได้เลือกหลักสูตร{' '}
          <NavLink to="/" className="text-seal underline underline-offset-2">
            เลือกจากรายการหลักสูตร
          </NavLink>
        </p>
      </div>
    )
  }

  const status = program?.session_status
  const awaiting = status === 'suspended'

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-rule bg-card px-6 py-3 lg:px-10">
      <div className="min-w-0">
        {/* Labelled, because the name alone is just a string: a designer with
            two curricula open in two tabs cannot tell which one this is. */}
        <p className="eyebrow">หลักสูตรที่กำลังทำงาน</p>
        <div className="flex flex-wrap items-baseline gap-x-3">
          {/* Deliberately not an h1 — the page below owns that. This is chrome
              naming the working context, not the heading of the document. */}
          <p className="font-record text-lg leading-tight text-body">
            {program?.name_th || program?.field || programId}
          </p>
          <span className="data text-xs text-faint">{programId}</span>
          {program?.faculty && <span className="text-xs text-mute">{program.faculty}</span>}
        </div>
      </div>
      {status && (
        <span
          className={[
            'ml-auto rounded-sm px-1.5 py-0.5 text-xs',
            awaiting ? 'bg-seal-soft text-seal' : 'text-mute',
          ].join(' ')}
        >
          {SESSION_STATUS_LABELS[status] ?? status}
        </span>
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
      <nav className="on-ink w-full shrink-0 bg-ink py-4 lg:sticky lg:top-0 lg:h-screen lg:w-[var(--rail-width)] lg:overflow-y-auto lg:py-6">
        <div className="px-6 pb-4 lg:px-6">
          <p className="eyebrow">MHESI · OBE</p>
          <p className="font-record mt-0.5 text-base leading-tight text-field">
            ออกแบบหลักสูตร
          </p>
        </div>

        <StageRail reached={reached} />

        <div className="mt-4 space-y-0.5 border-t border-ink-line px-3 pt-4">
          <RailLink to="/" label="หลักสูตรทั้งหมด" note="เลือกหลักสูตรที่จะทำงานด้วย" />
          <RailLink to="/pipeline" label="รันทั้งชุด" note="รันต่อเนื่องและอนุมัติทีละขั้น" />
        </div>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        {!picking && <ProgramBar program={program} programId={programId} creating={creating} />}
        <main className="flex-1 px-6 py-8 lg:px-10">
          <div className="mx-auto max-w-5xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
