// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useWebSocket } from '../useWebSocket'

class FakeWebSocket {
  static OPEN = 1
  static instances: FakeWebSocket[] = []
  readyState = FakeWebSocket.OPEN
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  constructor(public url: string) { FakeWebSocket.instances.push(this) }
  close = vi.fn(() => this.onclose?.({ code: 1000 }))
}

beforeEach(() => {
  FakeWebSocket.instances = []
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeWebSocket)
})
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('authenticated WebSocket', () => {
  it('does not connect without a session and never puts the token in the URL', () => {
    const { result, rerender, unmount } = renderHook(({ token }) => useWebSocket(token), {
      initialProps: { token: null as string | null },
    })
    expect(FakeWebSocket.instances).toHaveLength(0)
    rerender({ token: 'test-session-token' })
    const ws = FakeWebSocket.instances[0]
    expect(ws.url).not.toContain('test-session-token')
    act(() => ws.onopen?.())
    expect(JSON.parse(ws.send.mock.calls[0][0])).toEqual({ type: 'authenticate', token: 'test-session-token' })
    expect(result.current.connected).toBe(false)
    act(() => ws.onmessage?.({ data: JSON.stringify({ type: 'snapshot', payload: {} }) }))
    expect(result.current.connected).toBe(true)
    rerender({ token: null })
    expect(ws.close).toHaveBeenCalled()
    act(() => vi.runAllTimers())
    expect(FakeWebSocket.instances).toHaveLength(1)
    unmount()
  })

  it('clears the session on an authentication close and does not reconnect', () => {
    const expired = vi.fn()
    window.addEventListener('supersignal-session-expired', expired)
    const { unmount } = renderHook(() => useWebSocket('test-session-token'))
    const ws = FakeWebSocket.instances[0]
    act(() => ws.onclose?.({ code: 4001 }))
    expect(expired).toHaveBeenCalledOnce()
    act(() => vi.runAllTimers())
    expect(FakeWebSocket.instances).toHaveLength(1)
    unmount()
    window.removeEventListener('supersignal-session-expired', expired)
  })
})
