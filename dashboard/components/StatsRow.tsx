"use client";

import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Wallet,
  Sun,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { formatPct } from "@/lib/utils";
import type { Trade, AgentRun } from "@/types";

type Props = {
  trades: Trade[];
  runs: AgentRun[];
  initialPortfolio?: number;
  currentPrice?: number | null;
};

// ─── Trend badge ──────────────────────────────────────────────────────────────
function TrendBadge({ value }: { value: number }) {
  if (value > 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[9px] font-bold uppercase tracking-wider text-profit bg-profit/10 border border-profit/20 px-1.5 py-0.5 rounded-full">
        <ArrowUpRight size={9} />
        UP
      </span>
    );
  }
  if (value < 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[9px] font-bold uppercase tracking-wider text-loss bg-loss/10 border border-loss/20 px-1.5 py-0.5 rounded-full">
        <ArrowDownRight size={9} />
        DOWN
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-[9px] font-bold uppercase tracking-wider text-text-muted bg-white/5 border border-border-subtle px-1.5 py-0.5 rounded-full">
      <Minus size={9} />
      FLAT
    </span>
  );
}

// ─── Open positions badge ─────────────────────────────────────────────────────
function OpenBadge({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span className="inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider text-accent bg-accent/10 border border-accent/20 px-1.5 py-0.5 rounded-full">
      <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
      {count} OPEN
    </span>
  );
}

// ─── StatCard ─────────────────────────────────────────────────────────────────
type StatCardProps = {
  label: string;
  value: string;
  sub?: string;
  icon: React.ElementType;
  sentiment: "positive" | "negative" | "neutral";
  badge?: React.ReactNode;
};

function StatCard({ label, value, sub, icon: Icon, sentiment, badge }: StatCardProps) {
  const valueColor =
    sentiment === "positive"
      ? "text-profit"
      : sentiment === "negative"
      ? "text-loss"
      : "text-text-primary";

  const tintClass =
    sentiment === "positive"
      ? "before:absolute before:inset-0 before:bg-profit/[0.03] before:pointer-events-none"
      : sentiment === "negative"
      ? "before:absolute before:inset-0 before:bg-loss/[0.03] before:pointer-events-none"
      : "";

  return (
    <div
      className={[
        "rounded-2xl border border-border-subtle bg-surface p-5 relative overflow-hidden group",
        "hover:border-white/10 transition-all duration-200",
        tintClass,
      ].join(" ")}
    >
      {/* Icon */}
      <div className="absolute top-4 right-4 w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center text-text-muted group-hover:text-profit transition-colors">
        <Icon size={14} />
      </div>

      {/* Label */}
      <p className="text-[10px] font-semibold text-text-muted uppercase tracking-widest mb-2">
        {label}
      </p>

      {/* Value */}
      <p className={`text-3xl font-bold tabular-nums font-mono leading-none ${valueColor}`}>
        {value}
      </p>

      {/* Sub line + optional badge */}
      <div className="flex items-center gap-2 mt-2 flex-wrap">
        {sub && (
          <p className="text-[11px] text-text-muted leading-snug">{sub}</p>
        )}
        {badge}
      </div>
    </div>
  );
}

// ─── StatsRow ─────────────────────────────────────────────────────────────────
export default function StatsRow({
  trades,
  runs,
  initialPortfolio = 1000,
  currentPrice,
}: Props) {
  // Closed trades
  const closedTrades = trades.filter(
    (t) => t.pnl_usd !== null && t.closed_at !== null
  );
  const winningTrades = closedTrades.filter((t) => (t.pnl_usd ?? 0) > 0);
  const winRate =
    closedTrades.length > 0
      ? (winningTrades.length / closedTrades.length) * 100
      : null;

  // Realised PnL
  const realisedPnl = closedTrades.reduce((s, t) => s + (t.pnl_usd ?? 0), 0);

  // Unrealised PnL from open BUY trades
  const openTrades = trades.filter(
    (t) => t.closed_at === null && t.action === "BUY"
  );
  const unrealisedPnl = currentPrice
    ? openTrades.reduce(
        (s, t) => s + (currentPrice / t.entry_price - 1) * t.amount_usd,
        0
      )
    : 0;

  const totalPnl = realisedPnl + unrealisedPnl;
  const currentBalance = initialPortfolio + realisedPnl;

  // Today's PnL (UTC midnight)
  const todayStart = new Date();
  todayStart.setUTCHours(0, 0, 0, 0);
  const todayPnl = closedTrades
    .filter((t) => t.closed_at && new Date(t.closed_at) >= todayStart)
    .reduce((s, t) => s + (t.pnl_usd ?? 0), 0);

  const avgPnlPct =
    closedTrades.length > 0
      ? closedTrades.reduce((s, t) => s + (t.pnl_percent ?? 0), 0) /
        closedTrades.length
      : null;

  // Sentiments
  const balanceSentiment: StatCardProps["sentiment"] =
    currentBalance > initialPortfolio
      ? "positive"
      : currentBalance < initialPortfolio
      ? "negative"
      : "neutral";

  const totalSentiment: StatCardProps["sentiment"] =
    totalPnl > 0 ? "positive" : totalPnl < 0 ? "negative" : "neutral";

  const todaySentiment: StatCardProps["sentiment"] =
    todayPnl > 0 ? "positive" : todayPnl < 0 ? "negative" : "neutral";

  const winSentiment: StatCardProps["sentiment"] =
    winRate == null ? "neutral" : winRate >= 50 ? "positive" : "negative";

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {/* Balance */}
      <StatCard
        label="Current Balance"
        value={`$${currentBalance.toLocaleString("en-US", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}`}
        sub={`Started $${initialPortfolio.toLocaleString("en-US", {
          maximumFractionDigits: 0,
        })}`}
        icon={Wallet}
        sentiment={balanceSentiment}
        badge={<TrendBadge value={totalPnl} />}
      />

      {/* Total PnL */}
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
        sentiment={totalSentiment}
      />

      {/* Today's PnL */}
      <StatCard
        label="Today's P&L"
        value={`${todayPnl >= 0 ? "+" : ""}$${todayPnl.toFixed(2)}`}
        sub={
          openTrades.length > 0
            ? `Unrealised ${unrealisedPnl >= 0 ? "+" : ""}$${unrealisedPnl.toFixed(2)}`
            : "No open positions"
        }
        icon={Sun}
        sentiment={todaySentiment}
        badge={<OpenBadge count={openTrades.length} />}
      />

      {/* Win Rate */}
      <StatCard
        label="Win Rate"
        value={winRate != null ? `${winRate.toFixed(0)}%` : "—"}
        sub={`${winningTrades.length}W · ${closedTrades.length - winningTrades.length}L · ${trades.length} total`}
        icon={winRate != null && winRate >= 50 ? TrendingUp : TrendingDown}
        sentiment={winSentiment}
      />
    </div>
  );
}
