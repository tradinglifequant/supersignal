import React, { useCallback, useEffect, useState } from 'react'
import api from '../services/api'
import { AgentLog, SignalCandidate } from '../types'

export const AIAnalysis: React.FC = () => {
  const [candidates, setCandidates] = useState<SignalCandidate[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [logs, setLogs] = useState<AgentLog[]>([])

  const loadCandidates = useCallback(() => {
    api
      .get('/api/signals?limit=30')
      .then((r) => {
        setCandidates(r.data)
        setSelected((prev) => prev || (r.data[0] ? r.data[0].id : null))
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    loadCandidates()
    const iv = setInterval(loadCandidates, 5000)
    return () => clearInterval(iv)
  }, [loadCandidates])

  useEffect(() => {
    if (!selected) return
    api
      .get(`/api/agent-logs?candidate_id=${selected}&limit=20`)
      .then((r) => setLogs(r.data))
      .catch(() => {})
  }, [selected])

  const selectedCandidate = candidates.find((c) => c.id === selected)

  return (
    <div style={{ padding: 20, background: '#0f172a', minHeight: '100%' }}>
      <h2 style={{ color: '#e2e8f0' }}>AI Analysis</h2>
      <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 16 }}>
        <div style={{ background: '#1e293b', borderRadius: 10, border: '1px solid #334155', padding: 12 }}>
          <div style={{ fontWeight: 700, color: '#e2e8f0', marginBottom: 10 }}>
            Candidates ({candidates.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 600, overflow: 'auto' }}>
            {candidates.map((c) => (
              <div
                key={c.id}
                onClick={() => setSelected(c.id)}
                style={{
                  padding: 10,
                  borderRadius: 8,
                  background: selected === c.id ? '#334155' : '#0f172a',
                  border: '1px solid #334155',
                  cursor: 'pointer',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <b style={{ color: '#e2e8f0', fontFamily: 'monospace' }}>
                    {c.symbol} {c.direction}
                  </b>
                  <span
                    style={{
                      fontSize: 11,
                      background: '#0f172a',
                      color: c.status === 'APPROVED' ? '#10b981' : c.status === 'REJECTED' ? '#ef4444' : '#94a3b8',
                      padding: '2px 6px',
                      borderRadius: 6,
                    }}
                  >
                    {c.status}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
                  {parseFloat(c.change_pct).toFixed(2)}% @ {new Date(c.detected_at).toLocaleTimeString()}
                </div>
              </div>
            ))}
            {candidates.length === 0 && (
              <div style={{ color: '#64748b', fontSize: 12, textAlign: 'center', padding: 20 }}>
                No candidates yet — trigger scanner will create them.
              </div>
            )}
          </div>
        </div>

        <div style={{ background: '#1e293b', borderRadius: 10, border: '1px solid #334155', padding: 16 }}>
          {selectedCandidate ? (
            <>
              <div style={{ marginBottom: 12 }}>
                <h4 style={{ color: '#e2e8f0', margin: '0 0 8px 0' }}>
                  {selectedCandidate.symbol} {selectedCandidate.direction} — Snapshot
                </h4>
                <div
                  style={{
                    fontSize: 12,
                    color: '#94a3b8',
                    fontFamily: 'monospace',
                    background: '#0f172a',
                    padding: 12,
                    borderRadius: 8,
                    border: '1px solid #334155',
                  }}
                >
                  <div>
                    Now: {selectedCandidate.current_price} Ref: {selectedCandidate.reference_price} Δ{' '}
                    {parseFloat(selectedCandidate.change_pct).toFixed(2)}%
                  </div>
                  <div>
                    Window: {selectedCandidate.window_seconds}s • Detected:{' '}
                    {new Date(selectedCandidate.detected_at).toLocaleString()}
                  </div>
                  <div>EventKey: {selectedCandidate.event_key}</div>
                  {selectedCandidate.rejection_reason && (
                    <div style={{ color: '#f59e0b', marginTop: 6 }}>
                      Rejection: {selectedCandidate.rejection_reason}
                    </div>
                  )}
                </div>
              </div>

              <h4 style={{ color: '#e2e8f0' }}>Agents 1–6 Execution Trace</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {logs.length === 0 && (
                  <div style={{ color: '#64748b', fontSize: 13 }}>
                    No agent logs recorded for this candidate yet. When ThreeRouter is unconfigured or unavailable, the pipeline fails closed and records explicit error traces.
                  </div>
                )}
                {logs.map((log) => {
                  let parsed: any = null
                  try {
                    parsed = log.response_json ? JSON.parse(log.response_json) : null
                  } catch {
                    parsed = null
                  }
                  return (
                    <div
                      key={log.id}
                      style={{ background: '#0f172a', borderRadius: 8, padding: 12, border: '1px solid #334155' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <b style={{ color: '#38bdf8' }}>{log.agent_name}</b>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                          {log.latency_ms != null && (
                            <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace' }}>
                              {log.latency_ms}ms
                            </span>
                          )}
                          <span
                            style={{
                              fontSize: 11,
                              padding: '2px 6px',
                              borderRadius: 6,
                              background:
                                log.validation_status === 'VALID'
                                  ? '#065f46'
                                  : log.validation_status === 'TIMEOUT'
                                    ? '#7f1d1d'
                                    : '#92400e',
                              color: '#fff',
                            }}
                          >
                            {log.validation_status}
                          </span>
                        </div>
                      </div>
                      {parsed && parsed.decision && (
                        <div style={{ fontSize: 12, color: '#cbd5e1', marginTop: 8 }}>
                          <div>
                            Decision:{' '}
                            <b
                              style={{
                                color:
                                  parsed.decision === 'YES'
                                    ? '#10b981'
                                    : parsed.decision === 'NO'
                                      ? '#ef4444'
                                      : '#f59e0b',
                              }}
                            >
                              {parsed.decision}
                            </b>{' '}
                            {parsed.confidence != null && <span>• confidence {parsed.confidence}</span>}
                          </div>
                          {parsed.rationale && (
                            <div style={{ color: '#94a3b8', marginTop: 4 }}>Rationale: {parsed.rationale}</div>
                          )}
                          {parsed.evidence?.length > 0 && (
                            <div style={{ marginTop: 6 }}>
                              <div style={{ fontWeight: 600 }}>Evidence:</div>
                              <ul style={{ margin: '4px 0 0 16px', color: '#94a3b8' }}>
                                {parsed.evidence.map((e: string, i: number) => (
                                  <li key={i}>{e}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                          {parsed.missing_data?.length > 0 && (
                            <div style={{ color: '#f59e0b', marginTop: 6 }}>
                              Missing: {parsed.missing_data.join(', ')}
                            </div>
                          )}
                          {parsed.invalidation_conditions && (
                            <div style={{ fontSize: 11, color: '#64748b', marginTop: 6 }}>
                              Invalidation: {parsed.invalidation_conditions}
                            </div>
                          )}
                        </div>
                      )}
                      {log.error_message && (
                        <div style={{ fontSize: 12, color: '#f87171', marginTop: 8, fontFamily: 'monospace' }}>
                          Error: {log.error_message}
                        </div>
                      )}
                      <div style={{ fontSize: 11, color: '#64748b', marginTop: 8 }}>
                        {new Date(log.created_at).toLocaleString()} • {log.provider} • schema {log.schema_version}
                      </div>
                    </div>
                  )
                })}
              </div>
            </>
          ) : (
            <div style={{ color: '#64748b' }}>Select a candidate to view AI trace.</div>
          )}
        </div>
      </div>
    </div>
  )
}
