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
export default function SingleRedirect({ to, children }: { to: string; children: ReactNode }) {
  const { programId } = useProgram()
  const mode = useAgentMode(programId)
  if (!programId) return <>{children}</>
  if (mode === null) return <LoadingLine />
  if (mode === 'single') return <Navigate to={to} replace />
  return <>{children}</>
}
