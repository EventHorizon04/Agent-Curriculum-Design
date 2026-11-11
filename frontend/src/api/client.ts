import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { getApiKey, requestApiKey } from './apiKey'

// Relative on purpose: the API is served from whatever origin served this page —
// the Vite dev server (which proxies /programs and /health to :8000) in dev, and
// the tunnel hostname in a demo. A hardcoded localhost breaks the second case.
const api = axios.create({
  baseURL: '',
})

// Every write route needs the key (the backend leaves GETs open). The designer
// types it once per tab; it is never built into the bundle.
api.interceptors.request.use((config) => {
  const key = getApiKey()
  if (key) config.headers.set('X-API-Key', key)
  return config
})

type Retriable = InternalAxiosRequestConfig & { _keyRetried?: boolean }

api.interceptors.response.use(undefined, async (error: unknown) => {
  if (!(error instanceof AxiosError) || error.response?.status !== 401 || !error.config) {
    throw error
  }
  const config = error.config as Retriable
  if (config._keyRetried) throw error
  const key = await requestApiKey()
  if (!key) throw error
  config._keyRetried = true
  return api.request(config)
})

export default api
