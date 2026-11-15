import { useEffect, useState } from 'react'
import api from '../api/client'
import type { AgentMode } from '../constants/stages'

/**
 * The agent mode of the program being worked on, or null while it is unknown.
 *
 * Pages that must not call a multi-agent route for a single-agent program (the
 * skill list, for one) wait for a non-null answer before fetching. A program
 * that cannot be read falls back to 'multi', the mode every older row has.
 */
export function useAgentMode(programId: string): AgentMode | null {
  const [state, setState] = useState<{ id: string; mode: AgentMode } | null>(null)

  useEffect(() => {
    if (!programId) return
    let cancelled = false
    api
      .get<{ agent_mode?: AgentMode }>(`/programs/${programId}`)
      .then((r) => {
        if (!cancelled) setState({ id: programId, mode: r.data.agent_mode ?? 'multi' })
      })
      .catch(() => {
        if (!cancelled) setState({ id: programId, mode: 'multi' })
      })
    return () => {
      cancelled = true
    }
  }, [programId])

  return state && state.id === programId ? state.mode : null
}
