import React, { useEffect, useState } from 'react'
import api from '../../services/api'

interface Props {
  state: string
  onUpdate: () => void
}

export const EngineControls: React.FC<Props> = ({ state, onUpdate }) => {
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')
  const [showEmergencyModal, setShowEmergencyModal] = useState(false)
  const [emergencyReason, setEmergencyReason] = useState('dashboard emergency')
  const isRunning = state === 'RUNNING'

  useEffect(() => {
    if (!showEmergencyModal) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowEmergencyModal(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [showEmergencyModal])

  const handle = async (action: 'start' | 'stop' | 'emergency') => {
    setLoading(true)
    setErrorMsg('')
    try {
      if (action === 'start') await api.post('/api/engine/start', { confirm: true })
      if (action === 'stop') await api.post('/api/engine/stop', { confirm: true, reason: 'operator stop' })
      if (action === 'emergency') {
        await api.post('/api/engine/emergency-stop', { confirm: true, reason: emergencyReason || 'dashboard emergency' })
        setShowEmergencyModal(false)
      }
      onUpdate()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      const formatted =
        typeof detail === 'string'
          ? detail
          : detail?.issues
            ? `${detail.message}: ${detail.issues.join('; ')}`
            : detail
              ? JSON.stringify(detail)
              : e.message
      setErrorMsg(`Action failed: ${formatted}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ flex: 1, marginRight: 16 }}>
      <div
        style={{
          display: 'flex',
          gap: 10,
          padding: '12px 16px',
          background: '#1e293b',
          border: '1px solid #334155',
          borderRadius: 10,
          flexWrap: 'wrap',
        }}
      >
        <button
          onClick={() => handle('start')}
          disabled={loading || isRunning}
          style={{
            padding: '10px 18px',
            borderRadius: 8,
            background: isRunning ? '#334155' : '#10b981',
            color: '#fff',
            border: 'none',
            fontWeight: 700,
            cursor: loading || isRunning ? 'not-allowed' : 'pointer',
            opacity: isRunning ? 0.6 : 1,
          }}
        >
          ▶ Start Engine
        </button>
        <button
          onClick={() => handle('stop')}
          disabled={loading || !isRunning}
          style={{
            padding: '10px 18px',
            borderRadius: 8,
            background: '#f59e0b',
            color: '#0f172a',
            border: 'none',
            fontWeight: 700,
            cursor: loading || !isRunning ? 'not-allowed' : 'pointer',
            opacity: !isRunning ? 0.6 : 1,
          }}
        >
          ⏸ Stop New Entries
        </button>
        <button
          onClick={() => setShowEmergencyModal(true)}
          disabled={loading}
          style={{
            padding: '10px 18px',
            borderRadius: 8,
            background: '#ef4444',
            color: '#fff',
            border: '1px solid #fca5a5',
            fontWeight: 800,
            cursor: 'pointer',
          }}
        >
          ⛔ Emergency Stop
        </button>
        <span style={{ marginLeft: 'auto', alignSelf: 'center', color: '#94a3b8', fontSize: 12 }}>
          Stop keeps monitoring/protection active. Emergency flattens positions.
        </span>
      </div>

      {errorMsg && (
        <div
          style={{
            marginTop: 8,
            padding: '8px 12px',
            borderRadius: 8,
            background: '#7f1d1d',
            border: '1px solid #ef4444',
            color: '#fecaca',
            fontSize: 12,
            display: 'flex',
            justifyContent: 'space-between',
          }}
        >
          <span>{errorMsg}</span>
          <button
            onClick={() => setErrorMsg('')}
            style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 12 }}
          >
            Dismiss
          </button>
        </div>
      )}

      {showEmergencyModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="emergency-dialog-title"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.72)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 50,
            padding: 16,
          }}
        >
          <div
            style={{
              background: '#1e293b',
              border: '2px solid #ef4444',
              borderRadius: 12,
              maxWidth: 440,
              width: '100%',
              padding: 20,
              color: '#e2e8f0',
            }}
          >
            <h3 id="emergency-dialog-title" style={{ marginTop: 0, color: '#f87171' }}>
              ⛔ Confirm Emergency Stop
            </h3>
            <p style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.5 }}>
              This blocks all new entries immediately, submits reduce-only market closes for open bot positions, and cleans residual bot TP/SL orders.
            </p>
            <input
              value={emergencyReason}
              onChange={(e) => setEmergencyReason(e.target.value)}
              placeholder="Emergency reason"
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: 6,
                border: '1px solid #334155',
                background: '#0f172a',
                color: '#e2e8f0',
                marginBottom: 14,
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
              <button
                onClick={() => setShowEmergencyModal(false)}
                style={{
                  padding: '8px 14px',
                  borderRadius: 6,
                  background: '#334155',
                  border: 'none',
                  color: '#e2e8f0',
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => handle('emergency')}
                disabled={loading}
                style={{
                  padding: '8px 16px',
                  borderRadius: 6,
                  background: '#ef4444',
                  border: 'none',
                  color: '#fff',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                Confirm Flatten All
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
