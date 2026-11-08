// @vitest-environment jsdom
import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import api from '../services/api'

class MockWS {
  static OPEN = 1
  readyState = MockWS.OPEN
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  close = vi.fn()
}

describe('App authentication & operator session flow', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', MockWS)
    vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/health') {
        return { data: { status: 'ok', version: '0.1.0', environment: 'development', timestamp: new Date().toISOString() } } as any
      }
      if (url === '/api/engine/status') {
        return {
          data: {
            state: 'STOPPED',
            environment: 'development',
            binance_connected: false,
            ai_connected: false,
            db_connected: true,
            symbol_coverage: 4,
            open_positions: 0,
            unprotected_positions: 0,
            risk_blocks: [],
          },
        } as any
      }
      if (url === '/api/config') {
        return {
          data: {
            environment: 'development',
            binance_testnet: true,
            binance_configured: false,
            threerouter_configured: false,
            trigger_percentage: '1.5',
            trigger_window_seconds: 180,
            base_margin: '3.0',
            leverage: 10,
            max_concurrent_trades: 3,
            profit_reinvestment_pct: '25.0',
            max_trade_allocation: '25.0',
            daily_loss_limit: '15.0',
            max_drawdown_pct: '20.0',
            max_aggregate_exposure: '100.0',
            max_consecutive_losses: 5,
            max_slippage_bps: '20.0',
            taker_fee_bps: '5.0',
            candidate_ttl_seconds: 30,
            cooldown_seconds: 60,
            protection_deadline_seconds: 5,
          },
        } as any
      }
      if (url === '/api/metrics') {
        return {
          data: {
            starting_balance: '1000',
            current_equity: '1000',
            realized_pnl: '0',
            unrealized_pnl: '0',
            win_rate: '0.00',
            total_trades: 0,
            winning_trades: 0,
            losing_trades: 0,
            open_positions: 0,
            max_concurrent: 3,
            current_drawdown: '0.00',
            daily_pnl: '0',
          },
        } as any
      }
      return { data: [] } as any
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('does not poll /api/engine/status while unauthenticated, signs in via form submit, and revokes on Sign Out', async () => {
    const postSpy = vi.spyOn(api, 'post').mockImplementation(async (url: string) => {
      if (url === '/api/auth/login') {
        return { data: { access_token: 'jwt-test-token' } } as any
      }
      return { data: { status: 'revoked' } } as any
    })

    render(<App />)
    expect(screen.getByText(/Sign in to Super Signal/i)).toBeDefined()

    // Ensure private /api/engine/status was not called prior to login
    const calledUrlsBefore = (api.get as any).mock.calls.map((c: any[]) => c[0])
    expect(calledUrlsBefore).not.toContain('/api/engine/status')

    fireEvent.change(screen.getByPlaceholderText('Username'), { target: { value: 'operator' } })
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'strong-pass' } })
    fireEvent.submit(screen.getByText('Sign In').closest('form')!)

    await waitFor(() => {
      expect(screen.getByText('Sign Out')).toBeDefined()
    })
    expect(postSpy).toHaveBeenCalledWith('/api/auth/login', { username: 'operator', password: 'strong-pass' })

    const calledUrlsAfter = (api.get as any).mock.calls.map((c: any[]) => c[0])
    expect(calledUrlsAfter).toContain('/api/engine/status')

    fireEvent.click(screen.getByText('Sign Out'))
    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith('/api/auth/logout')
      expect(screen.getByText(/Sign in to Super Signal/i)).toBeDefined()
    })
  })
})
