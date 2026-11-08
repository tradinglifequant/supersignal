import React, { useCallback, useEffect, useState } from 'react'
import api from '../services/api'
import { Trade } from '../types'

export const History: React.FC = () => {
  const [trades, setTrades] = useState<Trade[]>([])
  const [symbol, setSymbol] = useState('')
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    const params = new URLSearchParams()
    if (symbol) params.set('symbol', symbol.toUpperCase())
    if (status) params.set('status', status)
    params.set('limit', '100')
    const res = await api.get(`/api/trades?${params.toString()}`).catch(() => ({ data: [] }))
    setTrades(res.data)
  }, [symbol, status])

  useEffect(() => {
    load()
  }, [load])

  const exportCsv = () => {
    const esc = (v: string) => `"${v.replace(/"/g, '""')}"`
    const rows = [
      ['id', 'symbol', 'direction', 'entry', 'exit', 'pnl', 'status', 'created_at'],
      ...trades.map((t) => [
        t.id,
        t.symbol,
        t.direction,
        t.entry_price || '',
        t.exit_price || '',
        t.realized_pnl || '',
        t.status,
        t.created_at,
      ]),
    ]
    const csv = rows.map((r) => r.map(esc).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'trades.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div style={{ padding: 20, background: '#0f172a', minHeight: '100%' }}>
      <h2 style={{ color: '#e2e8f0' }}>Trade History</h2>
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        <input
          placeholder="Symbol"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            border: '1px solid #334155',
            background: '#1e293b',
            color: '#e2e8f0',
          }}
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            border: '1px solid #334155',
            background: '#1e293b',
            color: '#e2e8f0',
          }}
        >
          <option value="">All statuses</option>
          <option value="CLOSED">CLOSED</option>
          <option value="PROTECTED">PROTECTED</option>
          <option value="OPEN">OPEN</option>
          <option value="EMERGENCY_CLOSED">EMERGENCY_CLOSED</option>
          <option value="FAILED">FAILED</option>
        </select>
        <button
          onClick={load}
          style={{
            padding: '8px 16px',
            borderRadius: 6,
            background: '#38bdf8',
            border: 'none',
            color: '#0f172a',
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          Filter
        </button>
        <button
          onClick={exportCsv}
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            background: '#1e293b',
            border: '1px solid #334155',
            color: '#e2e8f0',
            cursor: 'pointer',
          }}
        >
          Export CSV
        </button>
      </div>

      <div style={{ background: '#1e293b', borderRadius: 10, border: '1px solid #334155', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead style={{ background: '#0f172a', color: '#94a3b8' }}>
            <tr>
              <th style={{ textAlign: 'left', padding: '10px 12px' }}>ID</th>
              <th>Symbol</th>
              <th>Dir</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Qty</th>
              <th>P&L</th>
              <th>Status</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr key={t.id} style={{ borderBottom: '1px solid #1e293b', color: '#cbd5e1' }}>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 11 }}>{t.id.slice(0, 8)}</td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>{t.symbol}</td>
                <td style={{ padding: '10px 12px', color: t.direction === 'LONG' ? '#10b981' : '#ef4444' }}>
                  {t.direction}
                </td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>{t.entry_price || '-'}</td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>{t.exit_price || '-'}</td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>{t.position_size || '-'}</td>
                <td
                  style={{
                    padding: '10px 12px',
                    fontFamily: 'monospace',
                    color: t.realized_pnl && parseFloat(t.realized_pnl) >= 0 ? '#10b981' : '#ef4444',
                  }}
                >
                  {t.realized_pnl || '-'}
                </td>
                <td style={{ padding: '10px 12px' }}>
                  <span style={{ background: '#334155', color: '#fff', padding: '2px 6px', borderRadius: 6, fontSize: 11 }}>
                    {t.status}
                  </span>
                </td>
                <td style={{ padding: '10px 12px', fontSize: 11, color: '#64748b' }}>
                  {new Date(t.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
            {trades.length === 0 && (
              <tr>
                <td colSpan={9} style={{ padding: 20, textAlign: 'center', color: '#64748b' }}>
                  No trades yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
