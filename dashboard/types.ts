export type Trade = {
  id: number;
  strategy_id: number | null;
  symbol: string;
  action: "BUY" | "SELL";
  amount_usd: number;
  entry_price: number;
  exit_price: number | null;
  pnl_usd: number | null;
  pnl_percent: number | null;
  close_reason: "TP" | "SL" | "timeout" | "manual" | null;
  duration_hours: number | null;
  tx_hash: string | null;
  status: "pending" | "executed" | "dry_run" | "failed";
  executed_at: string | null;
  closed_at: string | null;
};

export type Strategy = {
  id: number;
  symbol: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  reasoning: string;
  timeframe: string;
  risk_level: "low" | "medium" | "high";
  backtest_passed: boolean | null;
  backtest_return: number | null;
  backtest_win_rate: number | null;
  status: "pending" | "approved" | "rejected";
  created_at: string;
};

export type AgentRun = {
  id: number;
  started_at: string;
  completed_at: string | null;
  strategies_generated: number;
  trades_executed: number;
  total_pnl: number;
  error_message: string | null;
};

export type Health = {
  status: string;
  environment: string;
  bnb_price: number | null;
};

export type CompassAxes = {
  trend: number;
  momentum: number;
  sentiment: number;
  volatility: number;
  stress: number;
};

export type AgentStatus = {
  environment: string;
  trading_pair: string;
  dry_run: boolean;
  max_position_usd: number;
  open_positions: number;
  competition_mode: boolean;
  signing_backend: "twak" | "web3";
  last_run: AgentRun | null;
  scheduled_jobs: Array<{ id: string; next_run: string }>;
  compass?: {
    compass_score: number;
    regime: string;
    axes: CompassAxes;
  } | null;
};

export type CompetitionStatus = {
  competition_mode: boolean;
  in_trading_window: boolean;
  days_remaining: number;
  trades_today: number;
  min_trades_met: boolean;
  drawdown_pct: number;
  drawdown_halt: boolean;
  drawdown_zone?: string;
  drawdown_zone_label?: string;
  drawdown_size_mult?: number;
  today_pnl: number;
  open_positions: number;
  stale_positions: number[];
  initial_portfolio_usd: number;
};

export type ActivityItem = {
  id: number;
  time: string;
  type: "trade" | "hold" | "rejected" | "skipped" | "error" | "running" | "completed";
  color: "green" | "yellow" | "orange" | "red" | "gray" | "blue";
  title: string;
  detail: string | null;
  reasoning: string | null;
  duration_s?: number | null;
  symbol?: string;
  entry_price?: number;
  take_profit?: number;
  stop_loss?: number;
  confidence?: number;
};

export type BotConfig = {
  paused: boolean;
  position_size_usd: number | null;
  min_confidence: number | null;
  claude_instruction: string | null;
  eligible_tokens: string[] | null;
  monitor_interval_minutes: number | null;
  updated_at: string | null;
};

export type RunResult = {
  status: "executed" | "skipped" | "error";
  run_id?: number;
  strategy_id?: number;
  trade_id?: number;
  action?: string;
  tx_hash?: string | null;
  swap_status?: string;
  pnl_usd?: number;
  backtest?: string;
  reason?: string;
  error?: string;
};

export type TokenScanToken = {
  symbol: string;
  rank: number;
  score: number;
  change_1h: number | null;
  change_4h: number | null;
  change_24h: number | null;
  volume_usdt: number | null;
  volume_spike: number | null;
  rsi_1h: number | null;
  rsi?: number;    // legacy compat
  price: number | null;
  sma20_distance: number | null;
  data_source: string | null;
  scanned_at?: string | null;
};

export type TokenScanResult = {
  top_tokens: TokenScanToken[];
  scanned: number;
};

export type TradeStats = {
  total_trades: number;
  win_count: number;
  loss_count: number;
  win_rate_pct: number;
  avg_profit_usd: number;
  avg_hold_hours: number;
  best_trade_pct: number;
  worst_trade_pct: number;
  total_realized_pnl: number;
};

export type PerformancePoint = {
  time: string;
  portfolio_value: number;
  realized_pnl: number;
  unrealized_pnl: number;
  open_positions: number;
  total_trades: number;
  win_count: number;
  loss_count: number;
};

export type TwakStatus = {
  twak_configured: boolean;
  twak_url: string | null;
  wallet_name: string;
  wallet_address: string | null;
  registration: Record<string, unknown>;
  balance: Record<string, { price_usdt?: number }>;
  guardrails: {
    max_position_usd: number;
    max_daily_loss_usd: number;
    max_drawdown_pct: number;
    max_position_hold_hours: number;
    eligible_tokens: string[];
  };
};
