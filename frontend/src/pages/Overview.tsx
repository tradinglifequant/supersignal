import React, { useCallback, useEffect, useState } from 'react'
import api from '../services/api'
import { Metrics, EngineStatus, PreflightReport } from '../types'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

export const Overview: React.FC<{ engine: EngineStatus | null }> = ({ engine }) => {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [equity, setEquity] = useState<any[]>([])
  const [preflight, setPreflight] = useState<PreflightReport | null>(null)

  const load = useCallback(() => {
    api.get('/api/metrics').then((r) => setMetrics(r.data)).catch(() => {})
    api.get('/api/metrics/equity-curve').then((r) => setEquity(r.data)).catch(() => {})
    api.get('/api/engine/preflight').then((r) => setPreflight(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const iv = setInterval(load, 5000)
    return () => clearInterval(iv)
  }, [load])

  const kpis = metrics
    ? [
        { label: 'Current Equity', value: `$${metrics.current_equity}`, sub: `Start: $${metrics.starting_balance}` },
        {
          label: 'Realized P&L',
          value: `$${metrics.realized_pnl}`,
          accent: parseFloat(metrics.realized_pnl) >= 0 ? '#10b981' : '#ef4444',
        },
        { label: 'Unrealized P&L', value: `$${metrics.unrealized_pnl}` },
        { label: 'Win Rate', value: `${metrics.win_rate}%`, sub: `${metrics.winning_trades}W / ${metrics.losing_trades}L` },
        { label: 'Total Trades', value: `${metrics.total_trades}` },
        { label: 'Open Positions', value: `${metrics.open_positions} / ${metrics.max_concurrent}` },
        { label: 'Drawdown', value: `${metrics.current_drawdown}%` },
        { label: 'Daily P&L', value: `$${metrics.daily_pnl}` },
      ]
    : []

  const openPositions = engine?.open_positions ?? 0
  const unprotectedPositions = engine?.unprotected_positions ?? 0
  const protectedPositions = Math.max(0, openPositions - unprotectedPositions)

  const env = engine?.trading_env ?? 'none'
  const gateColor = env === 'live' ? '#ef4444' : env === 'testnet' ? '#f59e0b' : '#64748b'

  return (
    <div style={{ padding: 20, background: '#0f172a', minHeight: '100%' }}>
      <h2 style={{ color: '#e2e8f0', marginBottom: 12 }}>Overview</h2>

      {/* Execution gate: makes "why is nothing trading" visible instead of implicit */}
      <div
        style={{
          background: '#1e293b',
          border: `1px solid ${gateColor}`,
          borderRadius: 10,
          padding: 16,
          marginBottom: 20,
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center' }}>
          <div style={{ fontSize: 13, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.5 }}>
            Execution Gate
          </div>
          <span style={{ color: gateColor, fontWeight: 600, fontSize: 14 }}>
            {env === 'live' ? 'LIVE — real money' : env === 'testnet' ? 'TESTNET' : 'DISABLED (no orders)'}
          </span>
          <span style={{ color: '#94a3b8', fontSize: 13 }}>
            AI gate: <strong style={{ color: '#e2e8f0' }}>{engine?.ai_gate_mode ?? 'threerouter'}</strong>
          </span>
          <span style={{ color: '#94a3b8', fontSize: 13 }}>
            Portfolio Margin:{' '}
            <strong style={{ color: '#e2e8f0' }}>{engine?.portfolio_margin ? 'yes' : 'no'}</strong>
          </span>
          <span style={{ color: '#94a3b8', fontSize: 13 }}>
            Live armed:{' '}
            <strong style={{ color: engine?.live_armed ? '#ef4444' : '#e2e8f0' }}>
              {engine?.live_armed ? 'YES' : 'no'}
            </strong>
          </span>
        </div>
        {(preflight?.blocking?.length ?? 0) > 0 && (
          <ul style={{ margin: '12px 0 0', paddingLeft: 18, color: '#fbbf24', fontSize: 13 }}>
            {preflight!.blocking.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        )}
        {preflight?.passed && env === 'none' && (
          <div style={{ marginTop: 12, color: '#94a3b8', fontSize: 13 }}>
            Account checks pass, but <code>TRADING_ENV=none</code> so no order can be placed.
          </div>
        )}
      </div>

      {/* KPI Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: 12,
          marginBottom: 20,
        }}
      >
        {kpis.map((k) => (
          <div
            key={k.label}
            style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}
          >
            <div style={{ fontSize: 12, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.5 }}>
              {k.label}
            </div>
            <div
              style={{
                fontSize: 22,
                fontWeight: 700,
                color: (k as any).accent || '#e2e8f0',
                fontFamily: 'monospace',
              }}
            >
              {k.value}
            </div>
            {(k as any).sub && <div style={{ fontSize: 11, color: '#64748b' }}>{(k as any).sub}</div>}
          </div>
        ))}
      </div>

      {/* Operational Status */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
          <h4 style={{ color: '#e2e8f0', margin: '0 0 8px 0' }}>Operational Status</h4>
          <div style={{ fontSize: 13, color: '#cbd5e1', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div>
              Engine: <b>{engine?.state || 'UNKNOWN'}</b>{' '}
              {engine?.reason && <span style={{ color: '#94a3b8' }}>({engine.reason})</span>}
            </div>
            <div>Environment: <b>{engine?.environment || '-'}</b></div>
            <div>Symbol coverage: <b>{engine?.symbol_coverage || 0}</b></div>
            <div>Open positions: <b>{openPositions}</b></div>
            <div>
              DB:{' '}
              <span style={{ color: engine?.db_connected ? '#10b981' : '#ef4444' }}>
                {engine?.db_connected ? 'OK' : 'ERROR'}
              </span>
            </div>
          </div>
        </div>
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
          <h4 style={{ color: '#e2e8f0', margin: '0 0 8px 0' }}>Risk Status</h4>
          <div style={{ fontSize: 13, color: '#cbd5e1' }}>
            <div>Daily loss limit enforced • Drawdown monitored • Aggregate exposure capped</div>
            {engine?.risk_blocks && engine.risk_blocks.length > 0 && (
              <div
                style={{
                  marginTop: 8,
                  padding: '6px 10px',
                  borderRadius: 6,
                  background: '#7f1d1d',
                  color: '#fecaca',
                  fontSize: 12,
                }}
              >
                Active blocks: {engine.risk_blocks.join(' | ')}
              </div>
            )}
            <div
              style={{
                marginTop: 8,
                padding: 10,
                background: '#0f172a',
                borderRadius: 6,
                border: '1px solid #334155',
              }}
            >
              <div style={{ fontWeight: 600 }}>Protection Health</div>
              <div
                style={{
                  fontSize: 12,
                  color: unprotectedPositions > 0 ? '#ef4444' : openPositions > 0 ? '#10b981' : '#94a3b8',
                }}
              >
                {unprotectedPositions > 0
                  ? `ALERT: ${unprotectedPositions} unprotected position(s) (${protectedPositions}/${openPositions} verified)`
                  : openPositions > 0
                    ? `All ${openPositions} open position(s) verified with TP/SL`
                    : 'Idle — 0 open positions'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Charts */}
      <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
        <h4 style={{ color: '#e2e8f0', margin: '0 0 12px 0' }}>Equity Curve</h4>
        {equity.length ? (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={equity}>
              <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
              <XAxis
                dataKey="captured_at"
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                tickFormatter={(v) => new Date(v).toLocaleTimeString()}
              />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8 }} />
              <Line type="monotone" dataKey="account_equity" stroke="#38bdf8" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ color: '#64748b', fontSize: 13, padding: 40, textAlign: 'center' }}>
            No equity data yet — start engine to capture live equity snapshots.
          </div>
        )}
      </div>
    </div>
  )
}
