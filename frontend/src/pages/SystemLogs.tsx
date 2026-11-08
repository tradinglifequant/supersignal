import React, { useEffect, useState } from 'react'
import api from '../services/api'

export const SystemLogs: React.FC = () => {
  const [logs, setLogs] = useState<any[]>([])
  const [level, setLevel] = useState('')

  const load = async () => {
    const params = new URLSearchParams()
    if (level) params.set('level', level)
    params.set('limit', '100')
    const r = await api.get(`/api/logs?${params.toString()}`).catch(() => ({ data: [] }))
    setLogs(r.data)
  }
  useEffect(() => { load(); const iv = setInterval(load, 5000); return () => clearInterval(iv) }, [level])

  return (
    <div style={{ padding: 20, background: '#0f172a', minHeight: '100%' }}>
      <h2 style={{ color: '#e2e8f0' }}>System Logs</h2>
      <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
        <select value={level} onChange={(e) => setLevel(e.target.value)} style={{ padding: '6px 12px', borderRadius: 6, background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155' }}>
          <option value="">All levels</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <button onClick={load} style={{ padding: '6px 12px', borderRadius: 6, background: '#38bdf8', border: 'none', color: '#0f172a', fontWeight: 700, cursor: 'pointer' }}>Refresh</button>
      </div>
      <div style={{ background: '#1e293b', borderRadius: 10, border: '1px solid #334155', overflow: 'hidden' }}>
        <div style={{ maxHeight: 600, overflow: 'auto', fontFamily: 'monospace', fontSize: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead style={{ background: '#0f172a', color: '#94a3b8', position: 'sticky', top: 0 }}>
              <tr><th style={{ textAlign: 'left', padding: '8px 12px' }}>Time</th><th style={{ padding: '8px 12px' }}>Level</th><th style={{ padding: '8px 12px' }}>Event</th><th style={{ textAlign: 'left', padding: '8px 12px' }}>Message</th></tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} style={{ borderBottom: '1px solid #1e293b', color: '#cbd5e1' }}>
                  <td style={{ padding: '8px 12px', color: '#64748b', whiteSpace: 'nowrap' }}>{new Date(l.created_at).toLocaleString()}</td>
                  <td style={{ padding: '8px 12px' }}><span style={{ padding: '2px 6px', borderRadius: 6, background: l.level === 'ERROR' ? '#7f1d1d' : l.level === 'WARNING' ? '#92400e' : '#334155', color: '#fff', fontSize: 11 }}>{l.level}</span></td>
                  <td style={{ padding: '8px 12px', color: '#38bdf8' }}>{l.event_code}</td>
                  <td style={{ padding: '8px 12px', color: '#e2e8f0' }}>{l.message_redacted}</td>
                </tr>
              ))}
              {logs.length === 0 && <tr><td colSpan={4} style={{ padding: 20, textAlign: 'center', color: '#64748b' }}>No logs yet — engine will emit structured, redacted logs.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
