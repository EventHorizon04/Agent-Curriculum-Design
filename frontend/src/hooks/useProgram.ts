import { useState, useCallback } from 'react'

const STORAGE_KEY = 'ca_program_id'

export function useProgram() {
  const [programId, _set] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) ?? ''
  )

  const setProgramId = useCallback((id: string) => {
    if (id) {
      localStorage.setItem(STORAGE_KEY, id)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
    _set(id)
  }, [])

  return { programId, setProgramId }
}
