import { AlertCircle, CheckCircle2, SkipForward, Clock } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { formatDuration, timeAgo } from "@/lib/utils";
import type { AgentRun } from "@/types";

type Props = {
  runs: AgentRun[];
};

function RunStatusIcon({ run }: { run: AgentRun }) {
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
  const hasError = !!run.error_message;
  const isRunning = !run.completed_at;
  const wasSkipped = !hasError && !isRunning && run.trades_executed === 0;

  const statusColor = hasError
    ? "text-loss"
    : isRunning
    ? "text-accent"
    : wasSkipped
    ? "text-text-muted"
    : "text-profit";

  const statusLabel = hasError
    ? "Error"
    : isRunning
    ? "Running"
    : wasSkipped
    ? "Skipped"
    : "Completed";

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

        {run.error_message && (
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
