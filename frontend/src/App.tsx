import React, { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import api, { setAccessToken } from './services/api'
import { TopBar } from './components/layout/TopBar'
import { Sidebar } from './components/layout/Sidebar'
import { EngineControls } from './components/common/EngineControls'
import { Overview } from './pages/Overview'
import { LiveScanner } from './pages/LiveScanner'
import { Positions } from './pages/Positions'
import { History } from './pages/History'
import { AIAnalysis } from './pages/AIAnalysis'
import { Configuration } from './pages/Configuration'
import { SystemLogs } from './pages/SystemLogs'
import { useWebSocket } from './hooks/useWebSocket'
import { ConfigResponse, EngineStatus, HealthResponse } from './types'

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [engine, setEngine] = useState<EngineStatus | null>(null)
  const [config, setConfig] = useState<ConfigResponse | null>(null)
  const [events, setEvents] = useState<any[]>([])
  const [token, setToken] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [h, e, c] = await Promise.all([
        api.get('/api/health'),
        api.get('/api/engine/status'),
        api.get('/api/config'),
      ])
      setHealth(h.data)
      setEngine(e.data)
      setConfig(c.data)
    } catch {
      // Handled by axios 401 interceptor or retried next interval
    }
  }, [])

  // Only poll authenticated operator endpoints once signed in
  useEffect(() => {
    if (!token) {
      api.get('/api/health').then((r) => setHealth(r.data)).catch(() => {})
      return
    }
    refresh()
    const iv = setInterval(refresh, 5000)
    return () => clearInterval(iv)
  }, [token, refresh])

  const { connected } = useWebSocket(token, (ev) => {
    setEvents((prev) => [ev, ...prev].slice(0, 20))
  })

  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [loginError, setLoginError] = useState('')
  const [sessionNotice, setSessionNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const handleLogin = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    setBusy(true)
    setLoginError('')
    try {
      const r = await api.post('/api/auth/login', loginForm)
      if (!r.data?.access_token) {
        setLoginError('Login succeeded but no access token was returned.')
        return
      }
      setSessionNotice('')
      setAccessToken(r.data.access_token)
      setToken(r.data.access_token)
      setLoginForm((form) => ({ ...form, password: '' }))
    } catch (err: any) {
      setLoginError('Login failed: ' + (err.response?.data?.detail || err.message))
    } finally {
      setBusy(false)
    }
  }

  const handleLogout = async () => {
    try {
      await api.post('/api/auth/logout')
    } catch {
      // Clear local session regardless
    }
    setAccessToken(null)
    setToken(null)
    setEngine(null)
    setConfig(null)
    setEvents([])
  }

  useEffect(() => {
    const expire = (event: Event) => {
      setAccessToken(null)
      setToken(null)
      setEngine(null)
      setConfig(null)
      setEvents([])
      // The api interceptor diagnoses the rejection while the token is still in
      // hand and hands the result over on the event, so a proxy that drops the
      // auth header is visible instead of looking like a wrong password.
      const d = (event as CustomEvent).detail
      if (d && d.token_verifies === false) {
        setSessionNotice(
          `Session rejected by the server (${d.failure_reason || 'unknown reason'}). ` +
            `Authorization header reached the server: ${d.authorization_header_present ? 'yes' : 'no'}. ` +
            `X-Access-Token reached the server: ${d.x_access_token_present ? 'yes' : 'no'}. ` +
            (d.authorization_header_present || d.x_access_token_present
              ? 'The token itself was rejected.'
              : 'Neither token header reached the server, so a proxy in front of the app is stripping it.')
        )
      } else {
        setSessionNotice('Your session ended. Please sign in again.')
      }
    }
    window.addEventListener('supersignal-session-expired', expire)
    return () => window.removeEventListener('supersignal-session-expired', expire)
  }, [])

  if (!token) {
    return (
      <div
        style={{
          minHeight: '100vh',
          background: '#0f172a',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <form
          onSubmit={handleLogin}
          style={{
            background: '#1e293b',
            padding: 24,
            borderRadius: 12,
            border: '1px solid #334155',
            width: 360,
          }}
        >
          <h2 style={{ color: '#e2e8f0', marginTop: 0 }}>Sign in to Super Signal 🎯</h2>
          {sessionNotice && (
            <div
              role="alert"
              style={{
                background: '#7f1d1d',
                border: '1px solid #ef4444',
                color: '#fecaca',
                borderRadius: 6,
                padding: '8px 10px',
                fontSize: 12,
                marginBottom: 12,
              }}
            >
              {sessionNotice}
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <input
              aria-label="Username"
              autoComplete="username"
              value={loginForm.username}
              onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })}
              placeholder="Username"
              style={{
                padding: '10px 12px',
                borderRadius: 6,
                border: '1px solid #334155',
                background: '#0f172a',
                color: '#e2e8f0',
              }}
            />
            <input
              aria-label="Password"
              autoComplete="current-password"
              type="password"
              value={loginForm.password}
              onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
              placeholder="Password"
              style={{
                padding: '10px 12px',
                borderRadius: 6,
                border: '1px solid #334155',
                background: '#0f172a',
                color: '#e2e8f0',
              }}
            />
            {loginError && <div style={{ color: '#ef4444', fontSize: 12 }}>{loginError}</div>}
            <button
              type="submit"
              disabled={busy}
              style={{
                padding: '10px 16px',
                borderRadius: 6,
                background: '#38bdf8',
                border: 'none',
                color: '#0f172a',
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              Sign In
            </button>
            <div style={{ fontSize: 11, color: '#64748b' }}>
              Configure operator credentials in the backend before signing in.
            </div>
          </div>
        </form>
      </div>
    )
  }

  return (
    <BrowserRouter>
      <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', background: '#0f172a' }}>
        <TopBar health={health || undefined} engine={engine} config={config} wsConnected={connected} />
        <div style={{ display: 'flex', flex: 1 }}>
          <Sidebar />
          <div style={{ flex: 1, overflow: 'auto' }}>
            <div style={{ padding: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <EngineControls state={engine?.state || 'STOPPED'} onUpdate={refresh} />
              <button
                onClick={handleLogout}
                style={{
                  padding: '10px 14px',
                  borderRadius: 8,
                  background: '#1e293b',
                  border: '1px solid #334155',
                  color: '#e2e8f0',
                  cursor: 'pointer',
                  fontSize: 12,
                  whiteSpace: 'nowrap',
                }}
              >
                Sign Out
              </button>
            </div>
            <Routes>
              <Route path="/" element={<Overview engine={engine} />} />
              <Route path="/scanner" element={<LiveScanner />} />
              <Route path="/positions" element={<Positions />} />
              <Route path="/history" element={<History />} />
              <Route path="/ai" element={<AIAnalysis />} />
              <Route path="/config" element={<Configuration />} />
              <Route path="/system" element={<SystemLogs />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </div>
        </div>
        <div
          style={{
            position: 'fixed',
            bottom: 10,
            right: 10,
            background: '#1e293b',
            border: '1px solid #334155',
            borderRadius: 8,
            padding: 10,
            fontSize: 11,
            color: '#94a3b8',
            maxWidth: 320,
            display: events.length ? 'block' : 'none',
          }}
        >
          <div style={{ fontWeight: 700, color: '#e2e8f0', marginBottom: 6 }}>Live Events (WS)</div>
          {events.slice(0, 5).map((e, i) => (
            <div key={i} style={{ borderBottom: '1px solid #1e293b', padding: '4px 0' }}>
              {e.type}: {JSON.stringify(e.payload)?.slice(0, 80)}
            </div>
          ))}
        </div>
      </div>
    </BrowserRouter>
  )
}
