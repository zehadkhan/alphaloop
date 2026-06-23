import { AlertCircle, CheckCircle2, SkipForward, Clock, ShieldOff } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { formatDuration, timeAgo } from "@/lib/utils";
import type { AgentRun } from "@/types";

type Props = {
  runs: AgentRun[];
};

const SKIP_LABELS: Record<string, string> = {
  extreme_fear:     "Gate: Extreme Fear",
  extreme_greed:    "Gate: Extreme Greed",
  btc_downtrend:    "Gate: BTC Downtrend",
  token_weak_7d:    "Gate: Token Weak 7d",
  unroutable_token: "Gate: No Route",
  HOLD:             "Claude: HOLD",
  low_confidence:   "Low Confidence",
  backtest_failed:  "Backtest Failed",
  risk_off_regime:  "Risk-Off Regime",
  max_positions_reached: "Max Positions",
  token_already_held:    "Already Held",
  ohlcv_unavailable:     "Data Unavailable",
  unreliable_data:       "Unreliable Data",
};

function parseSkipReason(msg: string): { label: string; detail: string } | null {
  if (!msg.startsWith("skip:")) return null;
  const parts = msg.split(":");
  const key   = parts[1] ?? "unknown";
  const label = SKIP_LABELS[key] ?? `Skipped: ${key}`;
  const extra = parts.slice(2).join(":");
  let detail  = "";
  if (key === "extreme_fear")    detail = `F&G = ${extra}/100`;
  else if (key === "extreme_greed")   detail = `F&G = ${extra}/100`;
  else if (key === "btc_downtrend")   detail = `BTC 80h: ${extra}%`;
  else if (key === "token_weak_7d")   detail = `${parts[2]} 7d: ${parts[3]}%`;
  else if (key === "unroutable_token") detail = parts[2] ?? "";
  return { label, detail };
}

function RunStatusIcon({ run }: { run: AgentRun }) {
  if (run.error_message?.startsWith("skip:")) {
    return <ShieldOff size={14} className="text-orange-400 shrink-0" />;
  }
  if (run.error_message) {
    return <AlertCircle size={14} className="text-loss shrink-0" />;
  }
  if (!run.completed_at) {
    return <Clock size={14} className="text-accent shrink-0 animate-pulse" />;
  }
  if (run.trades_executed === 0 && run.strategies_generated === 0) {
    return <SkipForward size={14} className="text-text-muted shrink-0" />;
  }
  return <CheckCircle2 size={14} className="text-profit shrink-0" />;
}

function RunRow({ run }: { run: AgentRun }) {
  const skip     = run.error_message ? parseSkipReason(run.error_message) : null;
  const hasError = !!run.error_message && !skip;
  const isRunning = !run.completed_at;
  const wasSkipped = !hasError && !skip && !isRunning && run.trades_executed === 0;

  const statusColor = skip
    ? "text-orange-400"
    : hasError
    ? "text-loss"
    : isRunning
    ? "text-accent"
    : wasSkipped
    ? "text-text-muted"
    : "text-profit";

  const statusLabel = skip?.label
    ?? (hasError ? "Error" : isRunning ? "Running" : wasSkipped ? "Skipped" : "Completed");

  return (
    <div className="flex items-start gap-3 py-3 border-b border-border-subtle/50 last:border-0 hover:bg-surface-2/50 px-2 -mx-2 rounded-lg transition-colors">
      <div className="mt-0.5">
        <RunStatusIcon run={run} />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-text-primary">
              Run #{run.id}
            </span>
            <span className={`text-xs font-medium ${statusColor}`}>{statusLabel}</span>
          </div>
          <span className="text-xs text-text-muted shrink-0">
            {timeAgo(run.started_at)}
          </span>
        </div>

        <div className="mt-1 flex items-center gap-3 text-xs text-text-muted">
          <span>
            {run.strategies_generated} strateg{run.strategies_generated !== 1 ? "ies" : "y"}
          </span>
          <span>·</span>
          <span>{run.trades_executed} trade{run.trades_executed !== 1 ? "s" : ""}</span>
          <span>·</span>
          <span>{formatDuration(run.started_at, run.completed_at)}</span>
          {run.total_pnl !== 0 && (
            <>
              <span>·</span>
              <span className={run.total_pnl > 0 ? "text-profit" : "text-loss"}>
                {run.total_pnl > 0 ? "+" : ""}${run.total_pnl.toFixed(4)}
              </span>
            </>
          )}
        </div>

        {skip?.detail && (
          <p className="mt-1 text-xs text-orange-400/70">{skip.detail}</p>
        )}

        {hasError && run.error_message && (
          <p className="mt-1.5 text-xs text-loss bg-loss/10 rounded px-2 py-1 break-all">
            {run.error_message.length > 120
              ? run.error_message.slice(0, 120) + "…"
              : run.error_message}
          </p>
        )}
      </div>
    </div>
  );
}

export default function AgentRuns({ runs }: Props) {
  const displayRuns = runs.slice(0, 5);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Recent Runs</CardTitle>
        <span className="text-xs text-text-muted">{runs.length} total</span>
      </CardHeader>
      <CardContent>
        {displayRuns.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-text-muted">
            <p className="text-sm">No runs yet</p>
          </div>
        ) : (
          <div>
            {displayRuns.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
