import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { LoadingLine } from './RunProgress'
import { useAgentMode } from '../hooks/useAgentMode'
import { useProgram } from '../hooks/useProgram'

/**
 * Guards the pages a single-agent program does not have (skill extraction, the
 * separate PLO review). A deep link or an old bookmark to one lands on the
 * stage that replaces it instead of on a page whose routes answer 409. Nothing
 * of the guarded page mounts until the mode is known, so it never fires a
 * request for a stage the program does not run.
 */
export default function SingleRedirect({
  to,
  children,
  notice,
}: {
  to?: string
  children: ReactNode
  /** Shown instead of redirecting, for a page with nowhere to redirect to. */
  notice?: string
}) {
  const { programId } = useProgram()
  const mode = useAgentMode(programId)
  if (!programId) return <>{children}</>
  if (mode === null) return <LoadingLine />
  if (mode === 'single') {
    return to ? <Navigate to={to} replace /> : <p className="notice notice-warn">{notice}</p>
  }
  return <>{children}</>
}
