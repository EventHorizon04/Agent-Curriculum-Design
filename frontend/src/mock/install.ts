/**
 * Mock mode: answer every API call in the browser.
 *
 * Loaded only by `npm run dev:mock` (vite --mode mock), through a dynamic
 * import in main.tsx that a normal build compiles away. In that mode the dev
 * server has no proxy at all, so even a call this file failed to intercept
 * could not reach the real backend on :8000 — it would 404 on the Vite server.
 *
 * Two doors are covered: the shared axios instance (every page but one) and
 * `window.fetch` (StakeholderNeeds' classify-stream, which reads an SSE body).
 */
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { AxiosError, AxiosHeaders, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import api from '../api/client'
import {
  clone,
  consumeFailNextRequest,
  getControls,
  hasStoredDb,
  isScenarioName,
  saveDb,
} from './db'
import { buildRouter, classifyStream, latencyFor, pause, tickSessions } from './handlers'
import type { MockResponse } from './router'
import { seedScenario } from './scenarios'
import MockPanel from './MockPanel'

const router = buildRouter()

const SERVER_ERROR: MockResponse = {
  status: 500,
  data: { detail: 'mock: จำลองข้อผิดพลาดของเซิร์ฟเวอร์' },
}

/** One request through the mock API, whichever door it came in by. */
async function dispatch(method: string, url: string, body: unknown): Promise<MockResponse> {
  const parsed = new URL(url, window.location.origin)
  const path = parsed.pathname
  tickSessions()

  if (consumeFailNextRequest()) {
    await pause(latencyFor('normal'))
    console.info(`[mock] ${method} ${path} → 500 (armed from the panel)`)
    return SERVER_ERROR
  }

  const match = router.match(method, path)
  if (!match) {
    const message = `mock: no handler for ${method} ${path}`
    console.warn(`[mock] ${message}`)
    return { status: 404, data: { detail: message } }
  }

  if (match.speed !== 'self') await pause(latencyFor(match.speed))
  const res = await match.handler({ method, path, params: match.params, query: parsed.searchParams, body })
  saveDb()
  // Handlers return live rows; the page must not be able to mutate the db.
  return res.data instanceof Blob || res.data === undefined ? res : { ...res, data: clone(res.data) }
}

// ----------------------------------------------------------------------------
// axios
// ----------------------------------------------------------------------------

function parseBody(data: unknown): unknown {
  if (typeof data !== 'string') return data ?? null
  try {
    return JSON.parse(data)
  } catch {
    return data
  }
}

api.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
  const method = (config.method ?? 'get').toUpperCase()
  const url = new URL(config.url ?? '', new URL(config.baseURL || '/', window.location.origin))
  if (config.params && typeof config.params === 'object') {
    for (const [k, v] of Object.entries(config.params as Record<string, unknown>)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
    }
  }

  const res = await dispatch(method, url.pathname + url.search, parseBody(config.data))
  let data: unknown = res.status === 204 ? '' : res.data
  if (config.responseType === 'blob' && !(data instanceof Blob)) {
    data = new Blob([JSON.stringify(data ?? null)], { type: 'application/json' })
  }

  const response: AxiosResponse = {
    data,
    status: res.status,
    statusText: res.status < 400 ? 'OK' : 'Error',
    headers: new AxiosHeaders({ 'content-type': res.contentType ?? 'application/json' }),
    config,
    request: { mock: true },
  }
  const valid = !config.validateStatus || config.validateStatus(res.status)
  if (valid) return response
  throw new AxiosError(
    `Request failed with status code ${res.status}`,
    res.status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST,
    config,
    response.request,
    response,
  )
}

// ----------------------------------------------------------------------------
// fetch — classify-stream only
// ----------------------------------------------------------------------------

const CLASSIFY_STREAM = /^\/programs\/([^/]+)\/evidence\/classify-stream\/?$/
const realFetch = window.fetch.bind(window)

/** The route's StreamingResponse: `data: {...}\n\n` per event, one evidence
 *  item at a time, classification written as each item is reached. */
function classifyStreamResponse(pid: string): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      await pause(latencyFor('normal'))
      tickSessions()
      const { events, apply } = classifyStream(pid)
      for (const event of events) {
        const e = event as { status: string; index?: number }
        if (e.status === 'progress' && e.index !== undefined) {
          await pause(getControls().latency ? 350 : 40)
          apply(e.index - 1)
          saveDb()
        }
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
      }
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'X-Accel-Buffering': 'no',
    },
  })
}

window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  const url = new URL(raw, window.location.origin)
  const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase()
  const ours = url.origin === window.location.origin

  const stream = ours && method === 'GET' ? CLASSIFY_STREAM.exec(url.pathname) : null
  if (stream) {
    if (consumeFailNextRequest()) {
      await pause(latencyFor('normal'))
      return new Response(JSON.stringify(SERVER_ERROR.data), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return classifyStreamResponse(decodeURIComponent(stream[1]))
  }

  if (ours && (url.pathname.startsWith('/programs') || url.pathname.startsWith('/health'))) {
    // Never to the network: in mock mode there is no backend to reach, and the
    // real one must not be touched by a click-through.
    const message = `mock: fetch ${method} ${url.pathname} has no mock handler — blocked`
    console.error(`[mock] ${message}`)
    throw new TypeError(message)
  }
  return realFetch(input, init)
}

// ----------------------------------------------------------------------------
// Scenario on load, and the panel
// ----------------------------------------------------------------------------

/** `?mock=<scenario>` seeds and selects on load, then leaves the URL clean so a
 *  reload does not reseed over what the designer has done since. */
const params = new URLSearchParams(window.location.search)
const requested = params.get('mock')
if (isScenarioName(requested)) {
  seedScenario(requested)
  params.delete('mock')
  const query = params.toString()
  window.history.replaceState(
    window.history.state,
    '',
    `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
  )
} else if (!hasStoredDb()) {
  seedScenario(getControls().scenario)
}

const host = document.createElement('div')
host.id = 'mock-panel-root'
document.body.appendChild(host)
createRoot(host).render(createElement(MockPanel))

console.info(
  '%c[mock] mock mode — every API call is answered in the browser; nothing reaches the backend',
  'color:#6e5400;background:#fbf5d2;padding:2px 6px',
)
