import { TrendingUp, BarChart2, DollarSign, Clock } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { formatPct, timeAgo } from "@/lib/utils";
import type { Trade, AgentRun } from "@/types";

type Props = {
  trades: Trade[];
  runs: AgentRun[];
};

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <Card>
      <CardContent className="pt-5">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <p className="text-xs font-medium text-text-muted uppercase tracking-wider">{label}</p>
            <p className={`text-2xl font-bold tabular-nums ${color}`}>{value}</p>
            {sub && <p className="text-xs text-text-muted">{sub}</p>}
          </div>
          <div className="p-2 rounded-lg bg-surface-2 border border-border-subtle">
            <Icon size={18} className={color} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function StatsRow({ trades, runs }: Props) {
  const closedTrades = trades.filter((t) => t.pnl_percent !== null);
  const winningTrades = closedTrades.filter((t) => (t.pnl_percent ?? 0) > 0);
  const winRate =
    closedTrades.length > 0
      ? (winningTrades.length / closedTrades.length) * 100
      : null;

  const totalPnlUsd = trades.reduce((s, t) => s + (t.pnl_usd ?? 0), 0);

  const totalPnlPct =
    closedTrades.length > 0
      ? closedTrades.reduce((s, t) => s + (t.pnl_percent ?? 0), 0) /
        closedTrades.length
      : null;

  const lastRun = runs[0] ?? null;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <StatCard
        label="Total Trades"
        value={String(trades.length)}
        sub={`${closedTrades.length} closed`}
        icon={BarChart2}
        color="text-text-primary"
      />
      <StatCard
        label="Win Rate"
        value={winRate != null ? `${winRate.toFixed(0)}%` : "—"}
        sub={`${winningTrades.length}W / ${closedTrades.length - winningTrades.length}L`}
        icon={TrendingUp}
        color={
          winRate == null
            ? "text-text-secondary"
            : winRate >= 50
            ? "text-profit"
            : "text-loss"
        }
      />
      <StatCard
        label="Total PnL"
        value={
          totalPnlUsd !== 0
            ? `${totalPnlUsd > 0 ? "+" : ""}$${totalPnlUsd.toFixed(2)}`
            : "$0.00"
        }
        sub={totalPnlPct != null ? `Avg ${formatPct(totalPnlPct)}` : undefined}
        icon={DollarSign}
        color={
          totalPnlUsd > 0
            ? "text-profit"
            : totalPnlUsd < 0
            ? "text-loss"
            : "text-text-secondary"
        }
      />
      <StatCard
        label="Last Run"
        value={lastRun ? timeAgo(lastRun.completed_at ?? lastRun.started_at) : "Never"}
        sub={
          lastRun
            ? `${lastRun.strategies_generated} strategies · ${lastRun.trades_executed} trades`
            : "No runs yet"
        }
        icon={Clock}
        color="text-text-secondary"
      />
    </div>
  );
}
