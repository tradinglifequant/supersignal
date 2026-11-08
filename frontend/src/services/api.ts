import axios from 'axios'

// Remove sessions written by older versions, then keep new sessions in memory only.
try {
  localStorage.removeItem('supersignal_token')
} catch {
  // Ignore unavailable storage in restricted test/browser contexts
}

// A reload requires signing in again.
let accessToken: string | null = null
export const setAccessToken = (token: string | null) => {
  accessToken = token
}
export const getAccessToken = () => accessToken

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  headers: { 'Content-Type': 'application/json' },
})

// The token is sent twice: some reverse proxies and sandbox preview tunnels
// forward custom headers but drop or rewrite `Authorization`. Both carry the same
// bearer token and the backend verifies them identically.
export const TOKEN_HEADER = 'X-Access-Token'

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
    config.headers[TOKEN_HEADER] = accessToken
  }
  return config
})

// Ask the backend which token-bearing headers actually arrived. Reveals no secret:
// only header presence and a failure reason. Uses the bare axios instance so it
// cannot recurse through the interceptor below.
const probeAuth = async (token: string | null) => {
  try {
    const r = await axios.get('/api/auth/diagnose', {
      headers: token ? { Authorization: `Bearer ${token}`, [TOKEN_HEADER]: token } : {},
    })
    return r.data
  } catch {
    return null
  }
}

export const diagnoseAuth = () => probeAuth(accessToken)

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // An old anonymous or previous-session request must not clear a newer login.
    const sentToken = error.config?.headers?.Authorization
    const stillCurrent =
      sentToken === `Bearer ${accessToken}` || error.config?.headers?.[TOKEN_HEADER] === accessToken
    if (error.response?.status === 401 && accessToken && stillCurrent) {
      // Diagnose while the token is still in hand; after clearing it the backend
      // could only ever report "no token received".
      const diagnosis = await probeAuth(accessToken)
      accessToken = null
      window.dispatchEvent(new CustomEvent('supersignal-session-expired', { detail: diagnosis }))
    }
    return Promise.reject(error)
  }
)

export default api

export const wsUrl = () => {
  const configured = import.meta.env.VITE_WS_URL
  if (configured) return configured
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/ws`
}
