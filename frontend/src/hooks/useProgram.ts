import { useCallback, useSyncExternalStore } from 'react'

const STORAGE_KEY = 'ca_program_id'

/**
 * The program every page reads and writes, shared by every caller.
 *
 * This used to hold the id in `useState`, which gave each component its own
 * copy: setting the program on one screen updated localStorage and that
 * component, and nothing else. Pages got away with it because they unmount on
 * navigation and re-read storage on the way back in — but StageLayout is the
 * layout, mounts once and never unmounts, so its copy froze at whatever was
 * selected when the app loaded and the program bar named the wrong curriculum
 * for the rest of the session.
 *
 * localStorage is the single source of truth and every subscriber is told when
 * it changes. The `storage` event covers other tabs, which only fire it for
 * *other* documents, so writes here notify local subscribers directly.
 */
const listeners = new Set<() => void>()

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange)
  window.addEventListener('storage', onChange)
  return () => {
    listeners.delete(onChange)
    window.removeEventListener('storage', onChange)
  }
}

/** A string, not an object — useSyncExternalStore compares snapshots by
 *  identity, and a fresh object every call would re-render without end. */
function getSnapshot(): string {
  return localStorage.getItem(STORAGE_KEY) ?? ''
}

export function useProgram() {
  const programId = useSyncExternalStore(subscribe, getSnapshot)

  const setProgramId = useCallback((id: string) => {
    if (id) {
      localStorage.setItem(STORAGE_KEY, id)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
    listeners.forEach((notify) => notify())
  }, [])

  return { programId, setProgramId }
}
