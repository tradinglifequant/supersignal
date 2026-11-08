import React, { useState } from 'react'
import api from '../../services/api'

interface Props {
  state: string
  onUpdate: () => void
}

export const EngineControls: React.FC<Props> = ({ state, onUpdate }) => {
  const [loading, setLoading] = useState(false)
  const isRunning = state === 'RUNNING'

  const handle = async (action: 'start' | 'stop' | 'emergency') => {
    if (action === 'emergency' && !window.confirm('EMERGENCY STOP will flatten open positions and block new entries. Confirm?')) return
    setLoading(true)
    try {
      if (action === 'start') await api.post('/api/engine/start', { confirm: true })
      if (action === 'stop') await api.post('/api/engine/stop', { confirm: true, reason: 'operator stop' })
      if (action === 'emergency') await api.post('/api/engine/emergency-stop', { confirm: true, reason: 'dashboard emergency' })
      onUpdate()
    } catch (e: any) {
      alert('Action failed: ' + (e.response?.data?.detail ? JSON.stringify(e.response.data.detail) : e.message))
    } finally { setLoading(false) }
  }

  return (
    <div style={{ display: 'flex', gap: 10, padding: '12px 16px', background: '#1e293b', border: '1px solid #334155', borderRadius: 10, marginBottom: 16 }}>
      <button onClick={() => handle('start')} disabled={loading || isRunning} style={{ padding: '10px 18px', borderRadius: 8, background: isRunning ? '#334155' : '#10b981', color: '#fff', border: 'none', fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer', opacity: isRunning ? 0.6 : 1 }}>▶ Start Engine</button>
      <button onClick={() => handle('stop')} disabled={loading || !isRunning} style={{ padding: '10px 18px', borderRadius: 8, background: '#f59e0b', color: '#0f172a', border: 'none', fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer', opacity: !isRunning ? 0.6 : 1 }}>⏸ Stop New Entries</button>
      <button onClick={() => handle('emergency')} disabled={loading} style={{ padding: '10px 18px', borderRadius: 8, background: '#ef4444', color: '#fff', border: '1px solid #fca5a5', fontWeight: 800, cursor: 'pointer' }}>⛔ Emergency Stop</button>
      <span style={{ marginLeft: 'auto', alignSelf: 'center', color: '#94a3b8', fontSize: 12 }}>Stop keeps monitoring/protection active. Emergency flattens positions.</span>
    </div>
  )
}
