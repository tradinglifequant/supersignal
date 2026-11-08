import { useEffect, useRef, useState, useCallback } from 'react'
import { wsUrl } from '../services/api'

type WSEvent = { type: string; payload: any; timestamp: string }

export function useWebSocket(token: string | null, onEvent?: (ev: WSEvent) => void) {
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    if (!token) {
      setConnected(false)
      return
    }
    let stopped = false
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined
    let attempts = 0
    const connect = () => {
      if (stopped) return
      const ws = new WebSocket(wsUrl())
      wsRef.current = ws
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'authenticate', token }))
      }
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'snapshot') {
            setConnected(true)
            attempts = 0
            ws.send(JSON.stringify({ type: 'subscribe', payload: { channel: 'all' } }))
          }
          onEventRef.current?.(data)
        } catch {
          console.warn('Invalid WebSocket event')
        }
      }
      ws.onclose = (event) => {
        setConnected(false)
        if (!stopped && event.code !== 4001 && event.code !== 4003 && attempts < 10) {
          const delay = Math.min(1000 * Math.pow(2, attempts++), 30000)
          reconnectTimer = setTimeout(connect, delay)
        }
        if (!stopped && event.code === 4001) {
          window.dispatchEvent(new Event('supersignal-session-expired'))
        }
      }
      ws.onerror = () => ws.close()
    }
    connect()
    return () => {
      stopped = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [token])

  const send = useCallback((msg: any) => {
    if (connected && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [connected])

  return { connected, send }
}
