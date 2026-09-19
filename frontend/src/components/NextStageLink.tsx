import { Link } from 'react-router-dom'
import { STAGES } from '../constants/stages'

/**
 * The step from one stage page to the next, in the one shape every page uses.
 *
 * The sequence and the label come from `STAGES`, so a page never spells its
 * successor's name: two pages carried a hardcoded "ดำเนินการต่อ → PLO Synthesis"
 * while the first two stages offered no way forward at all, and the designer had
 * to find the rail to continue.
 *
 * It navigates and nothing else. Immutable rule 7 puts a human at every stage
 * boundary, so moving to the next page is the designer's act of approving this
 * one — the next stage still runs only when they press its own run button.
 *
 * Shown even when the stage has produced nothing, disabled with the reason:
 * a designer who cannot continue is better told why than left looking for the
 * button. It sits at the foot of the page for the same reason — the checkpoint
 * is meant to be crossed after reading what is on the page, not from the header
 * above it.
 */
export default function NextStageLink({
  from,
  ready,
  blockedReason,
}: {
  /** Stage key of the page this is rendered on, as `STAGES` spells it. */
  from: string
  /** Has this stage produced what the next one reads? */
  ready: boolean
  /** Why not, in the designer's words. Shown in place of the button. */
  blockedReason?: string
}) {
  const here = STAGES.findIndex((s) => s.key === from)
  const next = here < 0 ? undefined : STAGES[here + 1]
  // The last stage has nowhere to go, and an unknown key is a caller bug that
  // must not render a button pointing at stage 1.
  if (!next) return null

  const label = `ดำเนินการต่อ → ขั้นที่ ${next.ordinal}: ${next.label}`

  return (
    <div className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-gray-200 pt-4">
      <p className="text-xs text-gray-500">
        ขั้นถัดไป — {next.summary}
        {next.gateNote && <span className="text-gray-400"> · {next.gateNote}</span>}
      </p>
      {ready ? (
        <Link
          to={next.route}
          className="shrink-0 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
        >
          {label}
        </Link>
      ) : (
        <span
          className="shrink-0 cursor-not-allowed rounded-lg bg-gray-100 px-4 py-2 text-sm font-medium text-gray-400"
          title={blockedReason}
          aria-disabled="true"
        >
          {label}
        </span>
      )}
      {!ready && blockedReason && (
        <p className="w-full text-xs text-amber-700">{blockedReason}</p>
      )}
    </div>
  )
}
