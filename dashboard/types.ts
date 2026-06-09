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

export type AgentStatus = {
  environment: string;
  trading_pair: string;
  dry_run: boolean;
  max_position_usd: number;
  last_run: AgentRun | null;
  scheduled_jobs: Array<{ id: string; next_run: string }>;
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
