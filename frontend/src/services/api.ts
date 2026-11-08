import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('supersignal_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      // Optional: redirect to login
      // window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api

export const wsUrl = () => {
  const base = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/api/ws'
  const token = localStorage.getItem('supersignal_token')
  return token ? `${base}?token=${token}` : base
}
