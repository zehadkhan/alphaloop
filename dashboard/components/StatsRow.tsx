import { TrendingUp, BarChart2, DollarSign, Wallet, Sun } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { formatPct } from "@/lib/utils";
import type { Trade, AgentRun } from "@/types";

type Props = {
  trades: Trade[];
  runs: AgentRun[];
  initialPortfolio?: number;
  currentPrice?: number | null;
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

export default function StatsRow({ trades, runs, initialPortfolio = 1000, currentPrice }: Props) {
  const closedTrades = trades.filter((t) => t.pnl_usd !== null && t.closed_at !== null);
  const winningTrades = closedTrades.filter((t) => (t.pnl_usd ?? 0) > 0);
  const winRate =
    closedTrades.length > 0
      ? (winningTrades.length / closedTrades.length) * 100
      : null;

  // Realised PnL from closed trades
  const realisedPnl = closedTrades.reduce((s, t) => s + (t.pnl_usd ?? 0), 0);

  // Unrealised PnL from open trades (using live price)
  const openTrades = trades.filter((t) => t.closed_at === null && t.action === "BUY");
  const unrealisedPnl = currentPrice
    ? openTrades.reduce((s, t) => {
        return s + ((currentPrice / t.entry_price - 1) * t.amount_usd);
      }, 0)
    : 0;

  const totalPnl = realisedPnl + unrealisedPnl;
  const currentBalance = initialPortfolio + realisedPnl; // balance excludes unrealised

  // Today's PnL — trades closed since UTC midnight
  const todayStart = new Date();
  todayStart.setUTCHours(0, 0, 0, 0);
  const todayPnl = closedTrades
    .filter((t) => t.closed_at && new Date(t.closed_at) >= todayStart)
    .reduce((s, t) => s + (t.pnl_usd ?? 0), 0);

  const avgPnlPct =
    closedTrades.length > 0
      ? closedTrades.reduce((s, t) => s + (t.pnl_percent ?? 0), 0) / closedTrades.length
      : null;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">

      {/* Balance */}
      <StatCard
        label="Current Balance"
        value={`$${currentBalance.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
        sub={`Started with $${initialPortfolio.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
        icon={Wallet}
        color={
          currentBalance > initialPortfolio
            ? "text-profit"
            : currentBalance < initialPortfolio
            ? "text-loss"
            : "text-text-primary"
        }
      />

      {/* Total PnL (realised + unrealised) */}
      <StatCard
        label="Total Profit / Loss"
        value={`${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`}
        sub={
          unrealisedPnl !== 0
            ? `${realisedPnl >= 0 ? "+" : ""}$${realisedPnl.toFixed(2)} closed · ${unrealisedPnl >= 0 ? "+" : ""}$${unrealisedPnl.toFixed(2)} open`
            : avgPnlPct != null
            ? `Avg ${formatPct(avgPnlPct)} per trade`
            : `${closedTrades.length} trades closed`
        }
        icon={DollarSign}
        color={totalPnl > 0 ? "text-profit" : totalPnl < 0 ? "text-loss" : "text-text-secondary"}
      />

      {/* Today's PnL */}
      <StatCard
        label="Today's P&L"
        value={`${todayPnl >= 0 ? "+" : ""}$${todayPnl.toFixed(2)}`}
        sub={
          openTrades.length > 0
            ? `${openTrades.length} position open · unrealised ${unrealisedPnl >= 0 ? "+" : ""}$${unrealisedPnl.toFixed(2)}`
            : "No open positions"
        }
        icon={Sun}
        color={todayPnl > 0 ? "text-profit" : todayPnl < 0 ? "text-loss" : "text-text-secondary"}
      />

      {/* Win Rate */}
      <StatCard
        label="Win Rate"
        value={winRate != null ? `${winRate.toFixed(0)}%` : "—"}
        sub={`${winningTrades.length} wins · ${closedTrades.length - winningTrades.length} losses · ${trades.length} total`}
        icon={TrendingUp}
        color={
          winRate == null
            ? "text-text-secondary"
            : winRate >= 50
            ? "text-profit"
            : "text-loss"
        }
      />

    </div>
  );
}
