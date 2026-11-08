import axios from 'axios'

// Remove sessions written by older versions, then keep new sessions in memory only.
localStorage.removeItem('supersignal_token')
// A reload requires signing in again.
let accessToken: string | null = null
export const setAccessToken = (token: string | null) => { accessToken = token }

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    // An old anonymous or previous-session request must not clear a newer login.
    if (error.response?.status === 401 && accessToken &&
        error.config?.headers?.Authorization === `Bearer ${accessToken}`) {
      accessToken = null
      window.dispatchEvent(new Event('supersignal-session-expired'))
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
