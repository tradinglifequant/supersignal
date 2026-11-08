import { useEffect, useRef, useState, useCallback } from 'react'
import { wsUrl } from '../services/api'

type WSEvent = { type: string; payload: any; timestamp: string }

export function useWebSocket(onEvent?: (ev: WSEvent) => void) {
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttempts = useRef(0)

  const connect = useCallback(() => {
    const url = wsUrl()
    try {
      const ws = new WebSocket(url)
      wsRef.current = ws
      ws.onopen = () => {
        setConnected(true)
        reconnectAttempts.current = 0
        // request snapshot
        ws.send(JSON.stringify({ type: 'subscribe', payload: { channel: 'all' } }))
      }
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          onEvent?.(data)
        } catch {}
      }
      ws.onclose = () => {
        setConnected(false)
        // exponential backoff reconnect
        if (reconnectAttempts.current < 10) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000)
          reconnectAttempts.current += 1
          setTimeout(connect, delay)
        }
      }
      ws.onerror = () => {
        ws.close()
      }
    } catch (e) {
      console.error('WS connect error', e)
    }
  }, [onEvent])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
    }
  }, [connect])

  const send = useCallback((msg: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  return { connected, send }
}
