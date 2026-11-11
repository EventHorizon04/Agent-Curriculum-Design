import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { getApiKey, requestApiKey } from './apiKey'

// Relative on purpose: the API is served from whatever origin served this page —
// the Vite dev server (which proxies /programs and /health to :8000) in dev, and
// the tunnel hostname in a demo. A hardcoded localhost breaks the second case.
const api = axios.create({
  baseURL: '',
})

// Every write route needs the key; GETs stay open, so the key is sent only on
// writes (the one GET that needs it goes through fetchWithKey). The designer
// types it once per tab; it is never built into the bundle.
const WRITE_METHODS = new Set(['post', 'put', 'patch', 'delete'])

api.interceptors.request.use((config) => {
  const key = getApiKey()
  if (key && WRITE_METHODS.has((config.method ?? 'get').toLowerCase())) {
    config.headers.set('X-API-Key', key)
  }
  return config
})

type Retriable = InternalAxiosRequestConfig & { _keyRetried?: boolean }

api.interceptors.response.use(undefined, async (error: unknown) => {
  if (!(error instanceof AxiosError) || error.response?.status !== 401 || !error.config) {
    throw error
  }
  const config = error.config as Retriable
  if (config._keyRetried) throw error
  // A key typed since this request went out (another request's dialog): retry
  // with it instead of asking again. The header it carried says what it sent.
  const sent = config.headers?.get?.('X-API-Key') ?? null
  const current = getApiKey()
  if (current !== sent) {
    config._keyRetried = true
    return api.request(config)
  }
  const key = await requestApiKey()
  if (!key) throw error
  config._keyRetried = true
  return api.request(config)
})

export default api
