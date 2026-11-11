// The API key the designer types, kept for this tab only. It is held in a
// module variable and mirrored to sessionStorage (so a reload keeps it); the
// variable is read first, so a key survives even when storage is blocked. It
// never reaches a URL, a log or localStorage.

const STORAGE_KEY = 'curriculum.apiKey'

let memoryKey: string | null = null

export function getApiKey(): string | null {
  if (memoryKey) return memoryKey
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) || null
  } catch {
    return null
  }
}

export function setApiKey(key: string): void {
  memoryKey = key
  try {
    window.sessionStorage.setItem(STORAGE_KEY, key)
  } catch {
    // Storage blocked: the module variable still holds it for this tab.
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
  const send = (): { response: Promise<Response>; sentKey: string | null } => {
    const headers = new Headers(init.headers)
    const key = getApiKey()
    if (key) headers.set('X-API-Key', key)
    return { response: fetch(input, { ...init, headers }), sentKey: key }
  }
  const attempt = send()
  const first = await attempt.response
  if (first.status !== 401) return first
  // A key typed for another request since this one went out: use it, no prompt.
  if (getApiKey() !== attempt.sentKey) return send().response
  const key = await requestApiKey()
  return key ? send().response : first
}
