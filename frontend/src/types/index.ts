export type EngineState =
  | 'STOPPED'
  | 'STARTING'
  | 'READY'
  | 'RUNNING'
  | 'STOPPING'
  | 'DEGRADED'
  | 'HALTED_RISK'
  | 'EMERGENCY'
  | 'ERROR'

export interface HealthResponse {
  status: string
  version: string
  environment: string
  timestamp: string
}

export interface ConfigResponse {
  environment: string
  trigger_percentage: string
  trigger_window_seconds: number
  base_margin: string
  leverage: number
  max_concurrent_trades: number
  profit_reinvestment_pct: string
  max_trade_allocation: string
  daily_loss_limit: string
  max_drawdown_pct: string
  max_aggregate_exposure: string
  max_consecutive_losses: number
  max_slippage_bps: string
  taker_fee_bps: string
  candidate_ttl_seconds: number
  cooldown_seconds: number
  protection_deadline_seconds: number
  binance_testnet: boolean
  binance_configured: boolean
  threerouter_configured: boolean
}

export interface SymbolInfo {
  symbol: string
  status: string
  contract_type: string
  margin_asset: string
  price_tick: string
  qty_step: string
  min_qty: string
  min_notional: string
  is_eligible: boolean
  ineligibility_reason?: string
  last_price?: string
  change_pct_180s?: string
}

export interface SignalCandidate {
  id: string
  event_key: string
  symbol: string
  direction: string
  current_price: string
  reference_price: string
  change_pct: string
  window_seconds: number
  detected_at: string
  expires_at: string
  status: string
  rejection_reason?: string
}

export interface Trade {
  id: string
  candidate_id?: string
  symbol: string
  side: string
  direction: string
  entry_order_client_id: string
  entry_price?: string
  exit_price?: string
  position_size?: string
  notional?: string
  margin_allocation: string
  leverage: number
  take_profit?: string
  stop_loss?: string
  modeled_max_loss?: string
  realized_pnl?: string
  fees?: string
  funding?: string
  status: string
  close_reason?: string
  created_at: string
  closed_at?: string
}

export interface Metrics {
  starting_balance: string
  current_equity: string
  realized_pnl: string
  unrealized_pnl: string
  win_rate: string
  total_trades: number
  winning_trades: number
  losing_trades: number
  open_positions: number
  max_concurrent: number
  current_drawdown: string
  daily_pnl: string
}

export interface EngineStatus {
  state: string
  environment: string
  changed_at?: string
  reason?: string
  risk_blocks?: string[]
  binance_connected: boolean
  ai_connected: boolean
  db_connected: boolean
  symbol_coverage: number
  open_positions: number
  unprotected_positions: number
}

export interface AgentLog {
  id: string
  candidate_id?: string
  agent_name: string
  provider: string
  model_or_agent_id?: string
  prompt_version?: string
  schema_version: string
  response_json?: string
  validation_status: string
  latency_ms?: number
  error_message?: string
  created_at: string
}
