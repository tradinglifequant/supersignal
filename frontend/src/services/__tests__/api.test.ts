// @vitest-environment jsdom
import axios from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import api, { TOKEN_HEADER, diagnoseAuth, getAccessToken, setAccessToken } from '../api'

/**
 * App.test.tsx mocks `api.get` wholesale, so the request/response interceptors —
 * the code that actually attaches the bearer token — were never executed by any
 * test. These tests run the real axios instance against a stub adapter.
 */

type Captured = { url?: string; headers: Record<string, any> }

describe('api bearer token handling', () => {
  let captured: Captured[]
  let respond: (config: any) => any

  beforeEach(() => {
    captured = []
    respond = () => ({ status: 200, statusText: 'OK', headers: {}, data: {}, config: {} })
    api.defaults.adapter = async (config: any) => {
      const headers: Record<string, any> = {}
      // Mirror how axios flattens AxiosHeaders before handing them to an adapter.
      for (const [k, v] of Object.entries(config.headers ?? {})) {
        if (typeof v === 'string') headers[k] = v
      }
      captured.push({ url: config.url, headers })
      const res = respond(config)
      if (res.status >= 400) {
        const err: any = new Error(`Request failed with status code ${res.status}`)
        err.response = { status: res.status, data: res.data ?? {}, headers: {}, config }
        err.config = config
        throw err
      }
      return { ...res, config }
    }
    setAccessToken(null)
  })

  afterEach(() => {
    setAccessToken(null)
    vi.restoreAllMocks()
  })

  it('sends the token in both Authorization and X-Access-Token', async () => {
    setAccessToken('tok-123')
    await api.get('/api/config')

    expect(captured).toHaveLength(1)
    expect(captured[0].headers.Authorization).toBe('Bearer tok-123')
    // A preview proxy that drops `Authorization` must not sign the operator out.
    expect(captured[0].headers[TOKEN_HEADER]).toBe('tok-123')
  })

  it('sends no token headers when signed out', async () => {
    await api.get('/api/health')
    expect(captured[0].headers.Authorization).toBeUndefined()
    expect(captured[0].headers[TOKEN_HEADER]).toBeUndefined()
  })

  it('clears the session and reports a diagnosis when the server rejects our token', async () => {
    setAccessToken('tok-123')
    let detail: any = 'unset'
    const expired = (e: Event) => {
      detail = (e as CustomEvent).detail
    }
    window.addEventListener('supersignal-session-expired', expired)

    respond = () => ({ status: 401, data: { detail: 'Invalid token' } })

    await expect(api.get('/api/config')).rejects.toBeTruthy()
    expect(getAccessToken()).toBeNull()
    // The probe runs on the bare axios instance (XHR in jsdom), so it resolves to
    // null here; what matters is that the event still fires and clears the token.
    expect(detail === null || typeof detail === 'object').toBe(true)
    window.removeEventListener('supersignal-session-expired', expired)
  })

  it('does not clear a newer session when a stale in-flight request 401s', async () => {
    setAccessToken('old-token')
    const stale = api.get('/api/config').catch(() => undefined)

    // Operator signs in again before the stale request resolves.
    setAccessToken('new-token')
    respond = (config: any) =>
      config.headers.Authorization === 'Bearer old-token'
        ? { status: 401, data: { detail: 'Invalid token' } }
        : { status: 200, data: {} }

    await stale
    expect(getAccessToken()).toBe('new-token')
  })

  it('diagnoseAuth forwards the token so the server can report what it saw', async () => {
    // probeAuth uses the bare axios instance so it cannot recurse through the
    // api interceptor, so stub that adapter separately.
    const seen: Record<string, any>[] = []
    axios.defaults.adapter = async (config: any) => {
      seen.push(config.headers as any)
      return { status: 200, statusText: 'OK', headers: {}, data: { token_verifies: true }, config } as any
    }
    setAccessToken('tok-123')

    const result = await diagnoseAuth()
    expect(result).toEqual({ token_verifies: true })
    expect(seen[0].Authorization).toBe('Bearer tok-123')
    expect(seen[0][TOKEN_HEADER]).toBe('tok-123')
  })

  it('diagnoseAuth returns null instead of throwing when the endpoint fails', async () => {
    axios.defaults.adapter = async (config: any) => {
      const err: any = new Error('boom')
      err.response = { status: 500, data: {}, headers: {}, config }
      err.config = config
      throw err
    }
    await expect(diagnoseAuth()).resolves.toBeNull()
  })
})
