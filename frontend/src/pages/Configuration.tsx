import React, { useEffect, useState } from 'react'
import api from '../services/api'
import { ConfigResponse } from '../types'

export const Configuration: React.FC = () => {
  const [cfg, setCfg] = useState<ConfigResponse | null>(null)
  const [form, setForm] = useState<Partial<Record<string, string>>>({})
  const [testResult, setTestResult] = useState<any>(null)
  const [cred, setCred] = useState({ api_key: '', api_secret: '', testnet: true })

  const load = async () => {
    const r = await api.get('/api/config').catch(() => null)
    if (r) { setCfg(r.data); setForm(r.data) }
  }
  useEffect(() => { load() }, [])

  const save = async () => {
    const payload: any = {}
    for (const k in form) if (form[k] !== cfg?.[k as keyof ConfigResponse]) payload[k] = form[k] ? parseFloat(form[k]!) : undefined
    // Only send changed numeric fields
    const numericPayload: any = {}
    if (form.trigger_percentage) numericPayload.trigger_percentage = form.trigger_percentage
    if (form.base_margin) numericPayload.base_margin = form.base_margin
    if (form.leverage) numericPayload.leverage = parseInt(form.leverage)
    if (form.max_concurrent_trades) numericPayload.max_concurrent_trades = parseInt(form.max_concurrent_trades)
    // etc.
    try {
      await api.put('/api/config', numericPayload)
      alert('Config saved')
      load()
    } catch (e: any) { alert('Save failed: ' + e.response?.data?.detail) }
  }

  const testCred = async () => {
    try {
      const r = await api.post('/api/config/credentials/test', { api_key: cred.api_key, api_secret: cred.api_secret, testnet: cred.testnet })
      setTestResult(r.data)
    } catch (e: any) { setTestResult({ valid: false, message: e.response?.data?.detail || e.message }) }
  }

  const saveCred = async () => {
    try {
      await api.post('/api/config/credentials', { api_key: cred.api_key, api_secret: cred.api_secret, exchange: 'binance', environment: cred.testnet ? 'testnet' : 'live' })
      alert('Credentials saved (encrypted)')
    } catch (e: any) { alert('Save failed: ' + e.response?.data?.detail) }
  }

  return (
    <div style={{ padding: 20, background: '#0f172a', minHeight: '100%' }}>
      <h2 style={{ color: '#e2e8f0' }}>Configuration</h2>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Exchange */}
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
          <h4 style={{ color: '#e2e8f0', marginTop: 0 }}>Exchange — Binance USDT-M Futures</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
            <label style={{ color: '#94a3b8' }}>Environment <select value={cred.testnet ? 'testnet' : 'live'} onChange={(e) => setCred({ ...cred, testnet: e.target.value === 'testnet' })} style={{ marginLeft: 8, padding: '6px 10px', borderRadius: 6, background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155' }}><option value="testnet">Testnet</option><option value="live">Live</option></select></label>
            <input placeholder="API Key" value={cred.api_key} onChange={(e) => setCred({ ...cred, api_key: e.target.value })} style={{ padding: '8px 12px', borderRadius: 6, border: '1px solid #334155', background: '#0f172a', color: '#e2e8f0' }} />
            <input placeholder="API Secret" type="password" value={cred.api_secret} onChange={(e) => setCred({ ...cred, api_secret: e.target.value })} style={{ padding: '8px 12px', borderRadius: 6, border: '1px solid #334155', background: '#0f172a', color: '#e2e8f0' }} />
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={testCred} style={{ padding: '8px 14px', borderRadius: 6, background: '#38bdf8', border: 'none', color: '#0f172a', fontWeight: 700, cursor: 'pointer' }}>Test Credentials</button>
              <button onClick={saveCred} style={{ padding: '8px 14px', borderRadius: 6, background: '#10b981', border: 'none', color: '#fff', fontWeight: 700, cursor: 'pointer' }}>Save Encrypted</button>
            </div>
            {testResult && <div style={{ padding: 10, borderRadius: 6, background: testResult.valid ? '#065f46' : '#7f1d1d', color: '#fff', fontSize: 12 }}>{testResult.message} {testResult.account_info && <pre style={{ marginTop: 6, background: 'rgba(0,0,0,0.2)', padding: 8, borderRadius: 6, overflow: 'auto' }}>{JSON.stringify(testResult.account_info, null, 2).slice(0, 500)}</pre>}</div>}
            <div style={{ fontSize: 11, color: '#64748b' }}>Credentials are encrypted at rest (Fernet) and never returned via API. Ensure API key has no withdrawal permission & IP allowlist set for production.</div>
          </div>
        </div>

        {/* ThreeRouter */}
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
          <h4 style={{ color: '#e2e8f0', marginTop: 0 }}>ThreeRouter AI</h4>
          <div style={{ fontSize: 13, color: '#94a3b8' }}>
            <div>API key status: {cfg?.threerouter_configured ? <span style={{ color: '#10b981' }}>Configured</span> : <span style={{ color: '#f59e0b' }}>Not configured (mock fallback active)</span>}</div>
            <div style={{ marginTop: 10, padding: 10, background: '#0f172a', borderRadius: 6, border: '1px solid #334155' }}>
              <div style={{ fontWeight: 600, color: '#e2e8f0' }}>Agents 1–6</div>
              <div style={{ fontSize: 12, marginTop: 6 }}>Agents run in parallel (1–5) then Agent 6 YES/NO. Missing evidence → fail-closed NO. Schema validated.</div>
            </div>
            <div style={{ marginTop: 10, fontSize: 11 }}>Provider base URL: https://api.threerouter.com (configurable). Set THREEROUTER_API_KEY in .env.</div>
          </div>
        </div>

        {/* Signal */}
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
          <h4 style={{ color: '#e2e8f0', marginTop: 0 }}>Signal</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
            <label style={{ color: '#cbd5e1' }}>Trigger % <input value={form.trigger_percentage || ''} onChange={(e) => setForm({ ...form, trigger_percentage: e.target.value })} style={{ marginLeft: 8, padding: '6px 10px', borderRadius: 6, background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155', width: 100 }} /> <span style={{ color: '#94a3b8' }}>default 1.5</span></label>
            <label style={{ color: '#cbd5e1' }}>Window seconds <input value={form.trigger_window_seconds || ''} onChange={(e) => setForm({ ...form, trigger_window_seconds: e.target.value })} style={{ marginLeft: 8, padding: '6px 10px', borderRadius: 6, background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155', width: 100 }} /> <span style={{ color: '#94a3b8' }}>default 180</span></label>
            <div style={{ fontSize: 11, color: '#64748b' }}>Trigger: ((P_now - P_180ago)/P_180ago)*100 via last traded price, Decimal arithmetic. Cooldown & TTL configurable.</div>
          </div>
        </div>

        {/* Risk */}
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
          <h4 style={{ color: '#e2e8f0', marginTop: 0 }}>Position & Risk (must be set before LIVE)</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 13 }}>
            <label style={{ color: '#cbd5e1' }}>Base margin <input value={form.base_margin || ''} onChange={(e) => setForm({ ...form, base_margin: e.target.value })} style={{ width: '100%', padding: '6px 10px', borderRadius: 6, background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155', marginTop: 4 }} /><div style={{ fontSize: 11, color: '#94a3b8' }}>default 3 USDT</div></label>
            <label style={{ color: '#cbd5e1' }}>Leverage <input value={form.leverage || ''} onChange={(e) => setForm({ ...form, leverage: e.target.value })} style={{ width: '100%', padding: '6px 10px', borderRadius: 6, background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155', marginTop: 4 }} /><div style={{ fontSize: 11, color: '#94a3b8' }}>default 10x</div></label>
            <label style={{ color: '#cbd5e1' }}>Max concurrent <input value={form.max_concurrent_trades || ''} onChange={(e) => setForm({ ...form, max_concurrent_trades: e.target.value })} style={{ width: '100%', padding: '6px 10px', borderRadius: 6, background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155', marginTop: 4 }} /><div style={{ fontSize: 11, color: '#94a3b8' }}>default 3</div></label>
            <label style={{ color: '#cbd5e1' }}>Reinvestment % <input value={form.profit_reinvestment_pct || ''} onChange={(e) => setForm({ ...form, profit_reinvestment_pct: e.target.value })} style={{ width: '100%', padding: '6px 10px', borderRadius: 6, background: '#0f172a', color: '#e2e8f0', border: '1px solid #334155', marginTop: 4 }} /><div style={{ fontSize: 11, color: '#94a3b8' }}>default 25</div></label>
          </div>
          <div style={{ marginTop: 10, fontSize: 12, color: '#cbd5e1' }}>
            <div>Daily loss limit: <b style={{ fontFamily: 'monospace' }}>{cfg?.daily_loss_limit}</b></div>
            <div>Max drawdown: <b>{cfg?.max_drawdown_pct}%</b></div>
            <div>Max aggregate exposure: <b>{cfg?.max_aggregate_exposure}</b></div>
            <div> modeled loss ≤ allocated margin incl. fees/slippage — not a guarantee against gaps.</div>
          </div>
          <button onClick={save} style={{ marginTop: 12, padding: '8px 16px', borderRadius: 6, background: '#38bdf8', border: 'none', color: '#0f172a', fontWeight: 700, cursor: 'pointer' }}>Save Config</button>
        </div>
      </div>
    </div>
  )
}
