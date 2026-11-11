// The API key the designer types, kept for this tab only. It is read from
// sessionStorage on every request so a key typed in the dialog takes effect at
// once, and it never reaches a URL, a log or localStorage.

const STORAGE_KEY = 'curriculum.apiKey'

export function getApiKey(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) || null
  } catch {
    return null
  }
}

export function setApiKey(key: string): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, key)
  } catch {
    // Storage blocked: the key lives only in the retried request.
  }
}

type Listener = () => void
const listeners = new Set<Listener>()
let pending: Promise<string | null> | null = null
let settle: ((key: string | null) => void) | null = null

/** Subscribe the dialog; returns the unsubscribe function. */
export function onKeyRequested(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Ask the designer for a key. Concurrent callers share one dialog and one
 *  answer; null means they cancelled (or no dialog is mounted to ask). */
export function requestApiKey(): Promise<string | null> {
  if (pending) return pending
  if (listeners.size === 0) return Promise.resolve(null)
  pending = new Promise<string | null>((resolve) => {
    settle = resolve
  })
  listeners.forEach((l) => l())
  return pending
}

/** Called by the dialog: a non-empty key is stored, null cancels. */
export function answerKeyRequest(key: string | null): void {
  const resolve = settle
  pending = null
  settle = null
  if (key) setApiKey(key)
  resolve?.(key)
}

/** `fetch` that sends the key and, on a 401, asks for one and retries once. */
export async function fetchWithKey(input: string, init: RequestInit = {}): Promise<Response> {
  const send = (): Promise<Response> => {
    const headers = new Headers(init.headers)
    const key = getApiKey()
    if (key) headers.set('X-API-Key', key)
    return fetch(input, { ...init, headers })
  }
  const first = await send()
  if (first.status !== 401) return first
  const key = await requestApiKey()
  return key ? send() : first
}
