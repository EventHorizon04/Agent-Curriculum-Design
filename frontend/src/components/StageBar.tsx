import { Link, NavLink } from 'react-router-dom'
import { AGENT_MODE_LABEL_TH, SESSION_STATUS_LABELS, type StageDef } from '../constants/stages'
import type { ProgramRow } from './StageLayout'

function statusClass(status: string): string {
  if (status === 'completed') return 'stamp'
  if (status === 'rejected' || status === 'failed') return 'stamp stamp-mandate'
  if (status === 'suspended') return 'stamp stamp-pending'
  return 'chip chip-neutral'
}

const SHELL = 'sticky top-12 z-30 border-b border-hair'
const SHELL_STYLE = {
  background: 'rgb(255 255 255 / 0.85)',
  backdropFilter: 'saturate(180%) blur(20px)',
  WebkitBackdropFilter: 'saturate(180%) blur(20px)',
} as const

/** Which program every page below is reading and writing, and how far it has
 *  got. Reached-ness comes from the program's own `current_stage`, never from
 *  which page happens to be open. */
export default function StageBar({
  program,
  programId,
  creating,
  stages,
  reached,
  pathname,
}: {
  program: ProgramRow | null
  programId: string | null
  creating: boolean
  stages: StageDef[]
  reached: number
  pathname: string
}) {
  if (!creating && !programId) {
    return (
      <div data-stage-bar className={`${SHELL} px-4 py-3 sm:px-6 lg:px-10`} style={SHELL_STYLE}>
        <p className="mx-auto w-full max-w-5xl text-sm text-pencil">
          ยังไม่ได้เลือกหลักสูตร{' '}
          <Link to="/my-programs" className="link">
            เลือกจากรายการหลักสูตร
          </Link>
        </p>
      </div>
    )
  }

  const status = creating ? null : program?.session_status
  const name = creating ? 'หลักสูตรใหม่' : program?.name_th || program?.field || programId
  const sub = creating
    ? null
    : [program?.faculty, program ? AGENT_MODE_LABEL_TH[program.agent_mode ?? 'multi'] : null]
        .filter(Boolean)
        .join(' · ')

  return (
    <div data-stage-bar className={`${SHELL} px-4 sm:px-6 lg:px-10`} style={SHELL_STYLE}>
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-4 gap-y-1 py-2">
        <div className="flex min-w-0 items-center gap-3">
          <div className="min-w-0">
            {/* Not an h1: the page below owns that. */}
            <p className="truncate text-base leading-snug font-semibold tracking-tight text-graphite">
              {name}
            </p>
            {sub && <p className="truncate text-[0.6875rem] leading-snug text-pencil">{sub}</p>}
            {creating && programId && (
              <p className="text-[0.6875rem] leading-snug text-pencil">
                หลักสูตรที่เลือกไว้: <span className="data">{programId}</span>
              </p>
            )}
          </div>
          {status && (
            <span className={`shrink-0 ${statusClass(status)}`}>
              {SESSION_STATUS_LABELS[status] ?? status}
            </span>
          )}
        </div>
        <nav aria-label="ขั้นตอนของหลักสูตร" className="ml-auto min-w-0 max-w-full">
        <ol className="flex gap-0.5 overflow-x-auto py-1 text-[0.8125rem] [scrollbar-width:none]">
          {stages.map((stage, i) => {
            const current = pathname === stage.route
            const done = i <= reached
            return (
              <li key={stage.key} className="shrink-0">
                <NavLink
                  to={stage.route}
                  title={`ขั้นที่ ${stage.ordinal} · ${stage.summary}${stage.gateNote ? ' · ' + stage.gateNote : ''}`}
                  className={[
                    'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 transition-colors',
                    current
                      ? 'bg-graphite text-white'
                      : done
                        ? 'text-graphite hover:bg-paper'
                        : 'text-pencil hover:bg-paper',
                  ].join(' ')}
                >
                  {done && !current && (
                    <span className="h-1.5 w-1.5 rounded-full bg-stamp" aria-hidden="true" />
                  )}
                  {stage.label}
                  {done && !current && <span className="sr-only"> — ผ่านแล้ว</span>}
                  {stage.gateNote && <span className="sr-only"> — {stage.gateNote}</span>}
                  {stage.gateNote && (
                    <svg
                      viewBox="0 0 16 16"
                      className={`h-3.5 w-3.5 ${current ? 'text-white' : 'text-stamp'}`}
                      aria-hidden="true"
                    >
                      <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" />
                      <path d="M5 8.2l2 2 4-4.4" fill="none" stroke="currentColor" strokeWidth="1.5" />
                    </svg>
                  )}
                </NavLink>
              </li>
            )
          })}
        </ol>
        </nav>
      </div>
    </div>
  )
}
