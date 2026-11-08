import React from 'react'
import { EngineStatus, HealthResponse } from '../../types'

interface Props {
  health?: HealthResponse
  engine: EngineStatus | null
  wsConnected: boolean
}

export const TopBar: React.FC<Props> = ({ health, engine, wsConnected }) => {
  const env = health?.environment || engine?.environment || 'development'
  const isLive = env === 'production'
  const state = engine?.state || 'STOPPED'
  const stateColor: Record<string, string> = {
    RUNNING: '#10b981',
    STOPPED: '#6b7280',
    STARTING: '#f59e0b',
    READY: '#3b82f6',
    STOPPING: '#f59e0b',
    HALTED_RISK: '#ef4444',
    EMERGENCY: '#dc2626',
    ERROR: '#ef4444',
    DEGRADED: '#f59e0b',
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 20px', background: '#0f172a', color: '#e2e8f0', borderBottom: '1px solid #1e293b', position: 'sticky', top: 0, zIndex: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontWeight: 800, fontSize: 18 }}>Super Signal 🎯</span>
        <span style={{ background: isLive ? '#dc2626' : '#10b981', color: '#fff', padding: '2px 10px', borderRadius: 999, fontSize: 12, fontWeight: 700, border: isLive ? '2px solid #fca5a5' : '1px solid #065f46' }}>
          {isLive ? 'LIVE' : 'TESTNET'}
        </span>
        <span style={{ background: stateColor[state] || '#6b7280', color: '#fff', padding: '2px 8px', borderRadius: 6, fontSize: 12, fontWeight: 600 }}>{state}</span>
        {engine?.symbol_coverage ? <span style={{ fontSize: 12, color: '#94a3b8' }}>{engine.symbol_coverage} symbols</span> : null}
      </div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 12 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: wsConnected ? '#10b981' : '#ef4444', display: 'inline-block' }} />
          WS {wsConnected ? 'connected' : 'offline'}
        </span>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: engine?.binance_connected ? '#10b981' : '#f59e0b', display: 'inline-block' }} title="Binance" />
        Binance
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: engine?.ai_connected ? '#10b981' : '#94a3b8', display: 'inline-block' }} title="ThreeRouter" />
        AI
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: engine?.db_connected ? '#10b981' : '#ef4444', display: 'inline-block' }} title="DB" />
        DB
        <span style={{ color: '#94a3b8' }}>v{health?.version || '0.1.0'}</span>
      </div>
    </div>
  )
}
