import axios from 'axios'

// Relative on purpose: the API is served from whatever origin served this page —
// the Vite dev server (which proxies /programs and /health to :8000) in dev, and
// the tunnel hostname in a demo. A hardcoded localhost breaks the second case.
const api = axios.create({
  baseURL: '',
})

export default api
