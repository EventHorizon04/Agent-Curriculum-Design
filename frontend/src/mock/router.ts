/**
 * A method + path-pattern router, just big enough for the mock API.
 *
 * Patterns use `:name` segments ("/programs/:pid/plos/:ploId/trace"). Literal
 * segments are tried before parameter segments, so `/plos/report/run` and
 * `/plos/export/matrix.xlsx` win over `/plos/:ploId/...` the same way FastAPI's
 * declaration order makes them win. Trailing slashes are ignored — the pages
 * call `/programs/` and `/programs/x/evidence/` with one.
 */

export interface MockRequest {
  method: string
  path: string
  params: Record<string, string>
  query: URLSearchParams
  body: unknown
}

export interface MockResponse {
  status: number
  data?: unknown
  /** Response content type; JSON when absent. */
  contentType?: string
}

export type Handler = (req: MockRequest) => MockResponse | Promise<MockResponse>

/** How long a route pretends to take: an ordinary request, a stage run, or
 *  'self' for a handler that sleeps on its own (it has to hold state across
 *  the wait, like the synthesis single-flight guard). */
export type Speed = 'normal' | 'slow' | 'self'

interface Route {
  method: string
  segments: string[]
  handler: Handler
  speed: Speed
}

export interface Match {
  handler: Handler
  params: Record<string, string>
  speed: Speed
}

function split(path: string): string[] {
  return path.split('/').filter(Boolean)
}

export class Router {
  private routes: Route[] = []

  add(method: string, pattern: string, handler: Handler, speed: Speed = 'normal'): this {
    this.routes.push({ method: method.toUpperCase(), segments: split(pattern), handler, speed })
    return this
  }

  get(pattern: string, handler: Handler, speed?: Speed): this {
    return this.add('GET', pattern, handler, speed)
  }

  post(pattern: string, handler: Handler, speed?: Speed): this {
    return this.add('POST', pattern, handler, speed)
  }

  put(pattern: string, handler: Handler, speed?: Speed): this {
    return this.add('PUT', pattern, handler, speed)
  }

  delete(pattern: string, handler: Handler, speed?: Speed): this {
    return this.add('DELETE', pattern, handler, speed)
  }

  match(method: string, path: string): Match | null {
    const parts = split(path).map((p) => decodeURIComponent(p))
    let best: { route: Route; params: Record<string, string>; literals: number } | null = null
    for (const route of this.routes) {
      if (route.method !== method.toUpperCase()) continue
      if (route.segments.length !== parts.length) continue
      const params: Record<string, string> = {}
      let literals = 0
      let ok = true
      for (let i = 0; i < parts.length; i++) {
        const seg = route.segments[i]
        if (seg.startsWith(':')) {
          params[seg.slice(1)] = parts[i]
        } else if (seg === parts[i]) {
          literals++
        } else {
          ok = false
          break
        }
      }
      if (ok && (!best || literals > best.literals)) best = { route, params, literals }
    }
    return best ? { handler: best.route.handler, params: best.params, speed: best.route.speed } : null
  }
}

/** FastAPI's error body. */
export function detail(status: number, message: string): MockResponse {
  return { status, data: { detail: message } }
}

export function ok(data: unknown, status = 200): MockResponse {
  return { status, data }
}
