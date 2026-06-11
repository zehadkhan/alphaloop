"use client";

import { Shield, TrendingDown, Calendar, BarChart2, AlertOctagon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { CompetitionStatus } from "@/types";

type Props = {
  status: CompetitionStatus | null;
};

function DrawdownBar({ pct }: { pct: number }) {
  const color =
    pct < 15 ? "bg-profit" : pct < 25 ? "bg-yellow-400" : "bg-loss";
  return (
    <div className="w-full h-1.5 rounded-full bg-surface-2 overflow-hidden">
      <div
        className={cn("h-full rounded-full transition-all duration-500", color)}
        style={{ width: `${Math.min(100, (pct / 30) * 100)}%` }}
      />
    </div>
  );
}

export default function CompetitionPanel({ status }: Props) {
  if (!status) return null;

  const ddColor =
    status.drawdown_pct < 15
      ? "text-profit"
      : status.drawdown_pct < 25
      ? "text-yellow-400"
      : "text-loss";

  return (
    <Card className={status.drawdown_halt ? "border-loss/40" : ""}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold text-text-primary flex items-center gap-2">
          <Shield size={14} className="text-accent" />
          Competition Status
          {!status.in_trading_window && (
            <span className="ml-auto text-[10px] text-text-muted font-normal">
              trading window not open yet
            </span>
          )}
        </CardTitle>
      </CardHeader>

      <CardContent className="pt-0 space-y-4">
        {status.drawdown_halt && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-loss/10 border border-loss/30 text-loss text-xs font-semibold">
            <AlertOctagon size={13} />
            TRADING HALTED — Drawdown limit reached
          </div>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {/* Portfolio drawdown */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-[10px] text-text-muted">
              <TrendingDown size={10} />
              Drawdown
            </div>
            <p className={cn("text-xl font-bold tabular-nums", ddColor)}>
              {status.drawdown_pct.toFixed(1)}%
            </p>
            <DrawdownBar pct={status.drawdown_pct} />
            <p className="text-[9px] text-text-muted">halt at {status.drawdown_halt ? "—" : "25%"} · DQ at 30%</p>
          </div>

          {/* Daily trade count */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-[10px] text-text-muted">
              <BarChart2 size={10} />
              Trades today
            </div>
            <p
              className={cn(
                "text-xl font-bold tabular-nums",
                status.min_trades_met ? "text-profit" : "text-yellow-400"
              )}
            >
              {status.trades_today}
              <span className="text-xs font-normal text-text-muted">/1 min</span>
            </p>
            <p className="text-[10px] text-text-muted">
              {status.min_trades_met ? "✓ minimum met" : "⚠ no trade yet today"}
            </p>
          </div>

          {/* Today PnL */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-[10px] text-text-muted">
              Today PnL
            </div>
            <p
              className={cn(
                "text-xl font-bold tabular-nums",
                status.today_pnl >= 0 ? "text-profit" : "text-loss"
              )}
            >
              {status.today_pnl >= 0 ? "+" : ""}${status.today_pnl.toFixed(2)}
            </p>
          </div>

          {/* Days remaining */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1 text-[10px] text-text-muted">
              <Calendar size={10} />
              Days left
            </div>
            <p className="text-xl font-bold tabular-nums text-text-primary">
              {status.in_trading_window ? status.days_remaining : "—"}
            </p>
            <p className="text-[10px] text-text-muted">
              {status.in_trading_window ? "in live window" : "Jun 22–28"}
            </p>
          </div>
        </div>

        {status.stale_positions.length > 0 && (
          <p className="text-[10px] text-yellow-400">
            ⚠ {status.stale_positions.length} position(s) held {">"}
            {" "}{20}h — will be force-closed before next cycle
          </p>
        )}
      </CardContent>
    </Card>
  );
}
