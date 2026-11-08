import React, { useEffect, useState } from 'react'
import api from '../services/api'
import { SymbolInfo, SignalCandidate } from '../types'

export const LiveScanner: React.FC = () => {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([])
  const [signals, setSignals] = useState<SignalCandidate[]>([])
  const [filter, setFilter] = useState<string>('all')
  const [query, setQuery] = useState('')

  const load = async () => {
    try {
      const [sRes, sigRes] = await Promise.all([api.get('/api/market/symbols'), api.get('/api/signals?limit=50')])
      setSymbols(sRes.data)
      setSignals(sigRes.data)
    } catch {}
  }
  useEffect(() => {
    load()
    const iv = setInterval(load, 3000)
    return () => clearInterval(iv)
  }, [])

  const filteredSignals = signals.filter((s) => {
    if (filter !== 'all' && s.status !== filter.toUpperCase()) return false
    if (query && !s.symbol.toLowerCase().includes(query.toLowerCase())) return false
    return true
  })

  return (
    <div style={{ padding: 20, background: '#0f172a', minHeight: '100%' }}>
      <h2 style={{ color: '#e2e8f0' }}>Live Market Scanner</h2>

      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <input placeholder="Search symbol (e.g., BTCUSDT)" value={query} onChange={(e) => setQuery(e.target.value)} style={{ padding: '8px 12px', borderRadius: 6, border: '1px solid #334155', background: '#1e293b', color: '#e2e8f0' }} />
        <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ padding: '8px 12px', borderRadius: 6, border: '1px solid #334155', background: '#1e293b', color: '#e2e8f0' }}>
          <option value="all">All</option>
          <option value="detected">Triggered</option>
          <option value="processing">Processing</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="expired">Expired</option>
        </select>
        <span style={{ color: '#94a3b8', fontSize: 13, alignSelf: 'center' }}>{symbols.filter((s) => s.is_eligible).length} eligible symbols</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 420px', gap: 16 }}>
        {/* Symbols Table */}
        <div style={{ background: '#1e293b', borderRadius: 10, border: '1px solid #334155', overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', borderBottom: '1px solid #334155', color: '#e2e8f0', fontWeight: 700 }}>Symbols</div>
          <div style={{ maxHeight: 500, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead style={{ position: 'sticky', top: 0, background: '#0f172a', color: '#94a3b8' }}>
                <tr><th style={{ textAlign: 'left', padding: '8px 12px' }}>Symbol</th><th style={{ padding: '8px 12px' }}>Tick</th><th style={{ padding: '8px 12px' }}>Step</th><th style={{ padding: '8px 12px' }}>Min Notional</th><th style={{ padding: '8px 12px' }}>Status</th></tr>
              </thead>
              <tbody>
                {symbols.slice(0, 100).map((s) => (
                  <tr key={s.symbol} style={{ borderBottom: '1px solid #1e293b', color: '#cbd5e1' }}>
                    <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontWeight: 600 }}>{s.symbol}</td>
                    <td style={{ padding: '8px 12px', fontFamily: 'monospace' }}>{s.price_tick}</td>
                    <td style={{ padding: '8px 12px', fontFamily: 'monospace' }}>{s.qty_step}</td>
                    <td style={{ padding: '8px 12px', fontFamily: 'monospace' }}>{s.min_notional}</td>
                    <td style={{ padding: '8px 12px' }}><span style={{ background: s.is_eligible ? '#065f46' : '#7f1d1d', color: '#fff', padding: '2px 6px', borderRadius: 6, fontSize: 11 }}>{s.is_eligible ? 'ELIGIBLE' : 'EXCLUDED'}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Signals */}
        <div style={{ background: '#1e293b', borderRadius: 10, border: '1px solid #334155', overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', borderBottom: '1px solid #334155', color: '#e2e8f0', fontWeight: 700 }}>Signal Queue / Candidate Status</div>
          <div style={{ maxHeight: 500, overflow: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filteredSignals.length === 0 && <div style={{ color: '#64748b', fontSize: 13, padding: 20, textAlign: 'center' }}>No signals - scanner will populate when 1.5% trigger occurs.</div>}
            {filteredSignals.map((sig) => (
              <div key={sig.id} style={{ background: '#0f172a', borderRadius: 8, padding: 12, border: '1px solid #334155' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#e2e8f0' }}>{sig.symbol} <span style={{ color: sig.direction === 'LONG' ? '#10b981' : '#ef4444' }}>{sig.direction}</span></span>
                  <span style={{ fontSize: 11, padding: '2px 6px', borderRadius: 6, background: sig.status === 'APPROVED' ? '#065f46' : sig.status === 'REJECTED' ? '#7f1d1d' : '#334155', color: '#fff' }}>{sig.status}</span>
                </div>
                <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 6, fontFamily: 'monospace' }}>
                  Now <b style={{ color: '#e2e8f0' }}>{sig.current_price}</b> Ref {sig.reference_price} Δ <b style={{ color: parseFloat(sig.change_pct) >= 0 ? '#10b981' : '#ef4444' }}>{sig.change_pct}%</b> / {sig.window_seconds}s
                </div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>{new Date(sig.detected_at).toLocaleString()} • expires {new Date(sig.expires_at).toLocaleTimeString()}</div>
                {sig.rejection_reason && <div style={{ fontSize: 11, color: '#f59e0b', marginTop: 6 }}>Reason: {sig.rejection_reason}</div>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
