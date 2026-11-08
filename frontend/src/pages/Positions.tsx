import React, { useCallback, useEffect, useState } from 'react'
import api from '../services/api'
import { Trade } from '../types'

export const Positions: React.FC = () => {
  const [open, setOpen] = useState<Trade[]>([])
  const [closed, setClosed] = useState<Trade[]>([])

  const load = useCallback(async () => {
    const [o, allTrades] = await Promise.all([
      api.get('/api/positions?status=OPEN').catch(() => ({ data: [] })),
      api.get('/api/trades?limit=50').catch(() => ({ data: [] })),
    ])
    setOpen(o.data)
    setClosed(
      (allTrades.data as Trade[]).filter((t) => t.status === 'CLOSED' || t.status === 'EMERGENCY_CLOSED')
    )
  }, [])

  useEffect(() => {
    load()
    const iv = setInterval(load, 3000)
    return () => clearInterval(iv)
  }, [load])

  return (
    <div style={{ padding: 20, background: '#0f172a', minHeight: '100%' }}>
      <h2 style={{ color: '#e2e8f0' }}>Positions</h2>

      <h4 style={{ color: '#e2e8f0', marginTop: 20 }}>Open Positions ({open.length})</h4>
      <div style={{ background: '#1e293b', borderRadius: 10, border: '1px solid #334155', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead style={{ background: '#0f172a', color: '#94a3b8' }}>
            <tr>
              <th style={{ textAlign: 'left', padding: '10px 12px' }}>Symbol/Side</th>
              <th style={{ padding: '10px 12px' }}>Qty</th>
              <th style={{ padding: '10px 12px' }}>Entry</th>
              <th style={{ padding: '10px 12px' }}>Notional</th>
              <th style={{ padding: '10px 12px' }}>Margin</th>
              <th style={{ padding: '10px 12px' }}>TP / SL</th>
              <th style={{ padding: '10px 12px' }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {open.length === 0 && (
              <tr>
                <td colSpan={7} style={{ padding: 20, textAlign: 'center', color: '#64748b' }}>
                  No open positions
                </td>
              </tr>
            )}
            {open.map((t) => (
              <tr key={t.id} style={{ borderBottom: '1px solid #1e293b', color: '#cbd5e1' }}>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>
                  <b>{t.symbol}</b>{' '}
                  <span style={{ color: t.direction === 'LONG' ? '#10b981' : '#ef4444' }}>{t.direction}</span>
                </td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>{t.position_size}</td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>{t.entry_price}</td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>{t.notional}</td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>
                  {t.margin_allocation} @{t.leverage}x
                </td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>
                  <div>TP {t.take_profit || '-'}</div>
                  <div>SL {t.stop_loss || '-'}</div>
                </td>
                <td style={{ padding: '10px 12px' }}>
                  <span
                    style={{
                      background: t.status === 'PROTECTED' ? '#065f46' : '#f59e0b',
                      color: '#fff',
                      padding: '2px 8px',
                      borderRadius: 6,
                      fontSize: 11,
                    }}
                  >
                    {t.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4 style={{ color: '#e2e8f0', marginTop: 24 }}>Closed Positions ({closed.length})</h4>
      <div style={{ background: '#1e293b', borderRadius: 10, border: '1px solid #334155', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead style={{ background: '#0f172a', color: '#94a3b8' }}>
            <tr>
              <th style={{ textAlign: 'left', padding: '10px 12px' }}>Symbol</th>
              <th style={{ padding: '10px 12px' }}>Entry/Exit</th>
              <th style={{ padding: '10px 12px' }}>P&L</th>
              <th style={{ padding: '10px 12px' }}>Close Reason</th>
              <th style={{ padding: '10px 12px' }}>Time</th>
            </tr>
          </thead>
          <tbody>
            {closed.length === 0 && (
              <tr>
                <td colSpan={5} style={{ padding: 20, textAlign: 'center', color: '#64748b' }}>
                  No closed trades
                </td>
              </tr>
            )}
            {closed.map((t) => (
              <tr key={t.id} style={{ borderBottom: '1px solid #1e293b', color: '#cbd5e1' }}>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>
                  {t.symbol} {t.direction}
                </td>
                <td style={{ padding: '10px 12px', fontFamily: 'monospace' }}>
                  {t.entry_price} → {t.exit_price || '-'}
                </td>
                <td
                  style={{
                    padding: '10px 12px',
                    fontFamily: 'monospace',
                    color: t.realized_pnl && parseFloat(t.realized_pnl) >= 0 ? '#10b981' : '#ef4444',
                  }}
                >
                  {t.realized_pnl || '-'}
                </td>
                <td style={{ padding: '10px 12px' }}>{t.close_reason || '-'}</td>
                <td style={{ padding: '10px 12px', fontSize: 11, color: '#64748b' }}>
                  {t.closed_at ? new Date(t.closed_at).toLocaleString() : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
