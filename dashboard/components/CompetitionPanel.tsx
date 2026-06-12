"use client";

import { Shield, TrendingDown, Calendar, BarChart2, AlertOctagon, Trophy } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { CompetitionStatus } from "@/types";

type Props = {
  status: CompetitionStatus | null;
};

function DrawdownBar({ pct }: { pct: number }) {
  const fill = pct < 15 ? "bg-profit" : pct < 25 ? "bg-amber-400" : "bg-loss";
  const width = Math.min(100, (pct / 30) * 100);
  return (
    <div className="w-full h-1 rounded-full bg-white/5 overflow-hidden mt-1.5">
      <div
        className={cn("h-full rounded-full transition-all duration-700", fill)}
        style={{ width: `${width}%` }}
      />
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  color,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub?: string;
  color: string;
  icon?: React.ElementType;
}) {
  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-1 text-[10px] text-text-muted font-medium uppercase tracking-widest">
        {Icon && <Icon size={9} />}
        {label}
      </div>
      <p className={cn("text-xl font-bold tabular-nums font-mono leading-tight", color)}>
        {value}
      </p>
      {sub && <p className="text-[10px] text-text-muted leading-tight">{sub}</p>}
    </div>
  );
}

export default function CompetitionPanel({ status }: Props) {
  if (!status) return null;

  const ddColor =
    status.drawdown_pct < 15 ? "text-profit" :
    status.drawdown_pct < 25 ? "text-amber-400" : "text-loss";

  const tradesToday = status.trades_today;
  const todayColor  = status.min_trades_met ? "text-profit" : "text-amber-400";

  return (
    <Card className={cn(status.drawdown_halt && "border-loss/40")}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-1.5">
            <Shield size={12} className="text-accent" />
            Competition
          </CardTitle>
          {status.in_trading_window ? (
            <span className="badge-live text-[10px]">LIVE</span>
          ) : (
            <span className="text-[10px] text-text-muted font-medium">Jun 22–28</span>
          )}
        </div>
      </CardHeader>

      <CardContent className="pt-0 space-y-4">

        {/* Halt warning */}
        {status.drawdown_halt && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-loss/10 border border-loss/25 text-loss text-xs font-semibold">
            <AlertOctagon size={12} />
            TRADING HALTED — drawdown limit hit
          </div>
        )}

        {/* Metrics grid */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-4">
          {/* Drawdown */}
          <div>
            <Metric
              label="Drawdown"
              value={`${status.drawdown_pct.toFixed(1)}%`}
              color={ddColor}
              icon={TrendingDown}
            />
            <DrawdownBar pct={status.drawdown_pct} />
            <p className="text-[9px] text-text-muted mt-1">halt 25% · DQ 30%</p>
          </div>

          {/* Trades today */}
          <Metric
            label="Today"
            value={`${tradesToday} trade${tradesToday !== 1 ? "s" : ""}`}
            sub={status.min_trades_met ? "✓ min met" : "⚠ need 1 trade"}
            color={todayColor}
            icon={BarChart2}
          />

          {/* Today P&L */}
          <Metric
            label="Today PnL"
            value={`${status.today_pnl >= 0 ? "+" : ""}$${status.today_pnl.toFixed(2)}`}
            color={status.today_pnl >= 0 ? "text-profit" : "text-loss"}
            icon={Trophy}
          />

          {/* Days left */}
          <Metric
            label="Days left"
            value={status.in_trading_window ? String(status.days_remaining) : "—"}
            sub={status.in_trading_window ? "in window" : "not started"}
            color="text-text-primary"
            icon={Calendar}
          />
        </div>

        {/* Stale positions warning */}
        {status.stale_positions.length > 0 && (
          <p className="text-[10px] text-amber-400 leading-relaxed">
            ⚠ {status.stale_positions.length} position(s) open &gt;20h — will force-close next cycle
          </p>
        )}

      </CardContent>
    </Card>
  );
}
