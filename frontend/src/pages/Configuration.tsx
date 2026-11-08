import React, { useCallback, useEffect, useState } from 'react'
import api from '../services/api'
import { ConfigResponse } from '../types'

const INT_FIELDS = new Set([
  'trigger_window_seconds',
  'leverage',
  'max_concurrent_trades',
  'max_consecutive_losses',
  'candidate_ttl_seconds',
  'cooldown_seconds',
  'protection_deadline_seconds',
])

const DECIMAL_FIELDS = new Set([
  'trigger_percentage',
  'base_margin',
  'profit_reinvestment_pct',
  'max_trade_allocation',
  'daily_loss_limit',
  'max_drawdown_pct',
  'max_aggregate_exposure',
  'max_slippage_bps',
  'taker_fee_bps',
])

export const Configuration: React.FC = () => {
  const [cfg, setCfg] = useState<ConfigResponse | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [statusBanner, setStatusBanner] = useState<{ ok: boolean; text: string } | null>(null)
  const [testResult, setTestResult] = useState<any>(null)
  const [cred, setCred] = useState({ api_key: '', api_secret: '', testnet: true })

  const load = useCallback(async () => {
    const r = await api.get('/api/config').catch(() => null)
    if (r) {
      setCfg(r.data)
      const strForm: Record<string, string> = {}
      for (const [k, v] of Object.entries(r.data)) {
        if (v !== null && v !== undefined) strForm[k] = String(v)
      }
      setForm(strForm)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const save = async () => {
    setStatusBanner(null)
    const payload: Record<string, any> = {}
    for (const key of DECIMAL_FIELDS) {
      if (form[key] !== undefined && form[key] !== '') {
        payload[key] = form[key]
      }
    }
    for (const key of INT_FIELDS) {
      if (form[key] !== undefined && form[key] !== '') {
        payload[key] = parseInt(form[key], 10)
      }
    }
    try {
      await api.put('/api/config', payload)
      setStatusBanner({ ok: true, text: 'Configuration saved & recorded in audit log.' })
      await load()
    } catch (e: any) {
      setStatusBanner({ ok: false, text: `Save failed: ${e.response?.data?.detail || e.message}` })
    }
  }

  const testCred = async () => {
    try {
      const r = await api.post('/api/config/credentials/test', {
        api_key: cred.api_key,
        api_secret: cred.api_secret,
        testnet: cred.testnet,
      })
      setTestResult(r.data)
    } catch (e: any) {
      setTestResult({ valid: false, message: e.response?.data?.detail || e.message })
    }
  }

  const saveCred = async () => {
    try {
      await api.post('/api/config/credentials', {
        api_key: cred.api_key,
        api_secret: cred.api_secret,
        exchange: 'binance',
        environment: cred.testnet ? 'testnet' : 'live',
      })
      setCred((prev) => ({ ...prev, api_key: '', api_secret: '' }))
      setTestResult({ valid: true, message: 'Credentials encrypted at rest & saved (secrets cleared from form).' })
      await load()
    } catch (e: any) {
      setTestResult({ valid: false, message: `Save failed: ${e.response?.data?.detail || e.message}` })
    }
  }

  const fieldInputStyle: React.CSSProperties = {
    width: '100%',
    padding: '6px 10px',
    borderRadius: 6,
    background: '#0f172a',
    color: '#e2e8f0',
    border: '1px solid #334155',
    marginTop: 4,
    fontFamily: 'monospace',
  }

  return (
    <div style={{ padding: 20, background: '#0f172a', minHeight: '100%' }}>
      <h2 style={{ color: '#e2e8f0' }}>Configuration</h2>

      {statusBanner && (
        <div
          style={{
            marginBottom: 16,
            padding: '10px 14px',
            borderRadius: 8,
            background: statusBanner.ok ? '#065f46' : '#7f1d1d',
            color: '#fff',
            fontSize: 13,
          }}
        >
          {statusBanner.text}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Exchange */}
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
          <h4 style={{ color: '#e2e8f0', marginTop: 0 }}>Exchange — Binance USDT-M Futures</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
            <div style={{ color: '#94a3b8' }}>
              Saved status:{' '}
              {cfg?.binance_configured ? (
                <span style={{ color: '#10b981', fontWeight: 600 }}>Configured</span>
              ) : (
                <span style={{ color: '#38bdf8', fontWeight: 600 }}>Not configured (Mock feed active)</span>
              )}
            </div>
            <label style={{ color: '#94a3b8' }}>
              Environment
              <select
                value={cred.testnet ? 'testnet' : 'live'}
                onChange={(e) => setCred({ ...cred, testnet: e.target.value === 'testnet' })}
                style={{
                  marginLeft: 8,
                  padding: '6px 10px',
                  borderRadius: 6,
                  background: '#0f172a',
                  color: '#e2e8f0',
                  border: '1px solid #334155',
                }}
              >
                <option value="testnet">Testnet</option>
                <option value="live">Live</option>
              </select>
            </label>
            <input
              placeholder="API Key (write-only)"
              value={cred.api_key}
              onChange={(e) => setCred({ ...cred, api_key: e.target.value })}
              style={{
                padding: '8px 12px',
                borderRadius: 6,
                border: '1px solid #334155',
                background: '#0f172a',
                color: '#e2e8f0',
              }}
            />
            <input
              placeholder="API Secret (write-only)"
              type="password"
              value={cred.api_secret}
              onChange={(e) => setCred({ ...cred, api_secret: e.target.value })}
              style={{
                padding: '8px 12px',
                borderRadius: 6,
                border: '1px solid #334155',
                background: '#0f172a',
                color: '#e2e8f0',
              }}
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={testCred}
                style={{
                  padding: '8px 14px',
                  borderRadius: 6,
                  background: '#38bdf8',
                  border: 'none',
                  color: '#0f172a',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                Test Credentials
              </button>
              <button
                onClick={saveCred}
                style={{
                  padding: '8px 14px',
                  borderRadius: 6,
                  background: '#10b981',
                  border: 'none',
                  color: '#fff',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                Save Encrypted
              </button>
            </div>
            {testResult && (
              <div
                style={{
                  padding: 10,
                  borderRadius: 6,
                  background: testResult.valid ? '#065f46' : '#7f1d1d',
                  color: '#fff',
                  fontSize: 12,
                }}
              >
                {testResult.message}
              </div>
            )}
            <div style={{ fontSize: 11, color: '#64748b' }}>
              Credentials are encrypted at rest (Fernet) and never returned via API. Ensure API key has no withdrawal permission & IP allowlist set for production.
            </div>
          </div>
        </div>

        {/* ThreeRouter */}
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
          <h4 style={{ color: '#e2e8f0', marginTop: 0 }}>ThreeRouter AI</h4>
          <div style={{ fontSize: 13, color: '#94a3b8' }}>
            <div>
              API key status:{' '}
              {cfg?.threerouter_configured ? (
                <span style={{ color: '#10b981', fontWeight: 600 }}>Configured</span>
              ) : (
                <span style={{ color: '#f59e0b', fontWeight: 600 }}>
                  Not configured (fail-closed rejection active)
                </span>
              )}
            </div>
            <div
              style={{
                marginTop: 10,
                padding: 10,
                background: '#0f172a',
                borderRadius: 6,
                border: '1px solid #334155',
              }}
            >
              <div style={{ fontWeight: 600, color: '#e2e8f0' }}>Agents 1–6</div>
              <div style={{ fontSize: 12, marginTop: 6 }}>
                Agents 1–5 run in parallel, followed by Agent 6 confirmation. Missing evidence, schema failure, or unconfigured API key always fails closed to NO.
              </div>
            </div>
            <div style={{ marginTop: 10, fontSize: 11 }}>
              Provider base URL: https://api.threerouter.com (configurable). Set THREEROUTER_API_KEY in .env.
            </div>
          </div>
        </div>

        {/* Signal */}
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
          <h4 style={{ color: '#e2e8f0', marginTop: 0 }}>Signal & Lifecycle</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 13 }}>
            <label style={{ color: '#cbd5e1' }}>
              Trigger %
              <input
                value={form.trigger_percentage || ''}
                onChange={(e) => setForm({ ...form, trigger_percentage: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Window seconds
              <input
                value={form.trigger_window_seconds || ''}
                onChange={(e) => setForm({ ...form, trigger_window_seconds: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Candidate TTL (s)
              <input
                value={form.candidate_ttl_seconds || ''}
                onChange={(e) => setForm({ ...form, candidate_ttl_seconds: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Cooldown (s)
              <input
                value={form.cooldown_seconds || ''}
                onChange={(e) => setForm({ ...form, cooldown_seconds: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
          </div>
          <div style={{ fontSize: 11, color: '#64748b', marginTop: 10 }}>
            Trigger: ((P_now - P_ref)/P_ref)*100 via last traded price using exact Decimal arithmetic.
          </div>
        </div>

        {/* Risk */}
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 16, border: '1px solid #334155' }}>
          <h4 style={{ color: '#e2e8f0', marginTop: 0 }}>Position & Hard Risk Limits</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 13 }}>
            <label style={{ color: '#cbd5e1' }}>
              Base margin (USDT)
              <input
                value={form.base_margin || ''}
                onChange={(e) => setForm({ ...form, base_margin: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Leverage (x)
              <input
                value={form.leverage || ''}
                onChange={(e) => setForm({ ...form, leverage: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Max concurrent trades
              <input
                value={form.max_concurrent_trades || ''}
                onChange={(e) => setForm({ ...form, max_concurrent_trades: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Profit reinvestment (%)
              <input
                value={form.profit_reinvestment_pct || ''}
                onChange={(e) => setForm({ ...form, profit_reinvestment_pct: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Max trade allocation (USDT)
              <input
                value={form.max_trade_allocation || ''}
                onChange={(e) => setForm({ ...form, max_trade_allocation: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Daily loss limit (USDT)
              <input
                value={form.daily_loss_limit || ''}
                onChange={(e) => setForm({ ...form, daily_loss_limit: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Max drawdown (%)
              <input
                value={form.max_drawdown_pct || ''}
                onChange={(e) => setForm({ ...form, max_drawdown_pct: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Max aggregate exposure (USDT)
              <input
                value={form.max_aggregate_exposure || ''}
                onChange={(e) => setForm({ ...form, max_aggregate_exposure: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Max consecutive losses
              <input
                value={form.max_consecutive_losses || ''}
                onChange={(e) => setForm({ ...form, max_consecutive_losses: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Max slippage (bps)
              <input
                value={form.max_slippage_bps || ''}
                onChange={(e) => setForm({ ...form, max_slippage_bps: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Taker fee (bps)
              <input
                value={form.taker_fee_bps || ''}
                onChange={(e) => setForm({ ...form, taker_fee_bps: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
            <label style={{ color: '#cbd5e1' }}>
              Protection deadline (s)
              <input
                value={form.protection_deadline_seconds || ''}
                onChange={(e) => setForm({ ...form, protection_deadline_seconds: e.target.value })}
                style={fieldInputStyle}
              />
            </label>
          </div>
          <div style={{ marginTop: 10, fontSize: 11, color: '#94a3b8' }}>
            Modeled loss ≤ allocated margin incl. fees/slippage — modeled risk bound, not a guarantee against market gaps.
          </div>
          <button
            onClick={save}
            style={{
              marginTop: 12,
              padding: '8px 16px',
              borderRadius: 6,
              background: '#38bdf8',
              border: 'none',
              color: '#0f172a',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            Save Config
          </button>
        </div>
      </div>
    </div>
  )
}
