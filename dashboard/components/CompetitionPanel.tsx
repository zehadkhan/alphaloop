"use client";

import { Shield, TrendingDown, Calendar, BarChart2, AlertOctagon, Trophy, Activity } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { CompetitionStatus, AgentStatus } from "@/types";

type Props = {
  status: CompetitionStatus | null;
  agentStatus?: AgentStatus | null;
};

const ZONE_COLORS: Record<string, string> = {
  GREEN:  "bg-profit/15 text-profit border-profit/30",
  YELLOW: "bg-amber-400/15 text-amber-400 border-amber-400/30",
  ORANGE: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  RED:    "bg-loss/15 text-loss border-loss/30",
  HALT:   "bg-loss/20 text-loss border-loss/40",
};

const REGIME_COLORS: Record<string, string> = {
  MOMENTUM_RIDE:    "text-profit",
  TREND_CONFIRM:    "text-profit/80",
  NEUTRAL_CAUTIOUS: "text-amber-400",
  DEFENSIVE:        "text-orange-400",
  RISK_OFF:         "text-loss",
};

function DrawdownBar({ pct }: { pct: number }) {
  const fill  = pct < 8 ? "bg-profit" : pct < 15 ? "bg-amber-400" : pct < 22 ? "bg-orange-400" : "bg-loss";
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

function CompassBar({ score, regime }: { score: number; regime: string }) {
  const width  = Math.min(100, (score / 50) * 100);
  const fill   =
    score >= 35 ? "bg-profit" :
    score >= 25 ? "bg-profit/70" :
    score >= 15 ? "bg-amber-400" :
    score >= 8  ? "bg-orange-400" : "bg-loss";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-text-muted font-medium uppercase tracking-widest flex items-center gap-1">
          <Activity size={9} />
          Compass
        </span>
        <span className={cn("font-bold font-mono", REGIME_COLORS[regime] ?? "text-text-primary")}>
          {score.toFixed(1)}/50
        </span>
      </div>
      <div className="w-full h-1.5 rounded-full bg-white/5 overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-700", fill)}
          style={{ width: `${width}%` }}
        />
      </div>
      <p className={cn("text-[10px] font-medium", REGIME_COLORS[regime] ?? "text-text-muted")}>
        {regime.replace(/_/g, " ")}
      </p>
    </div>
  );
}

function Metric({
  label, value, sub, color, icon: Icon,
}: {
  label: string; value: string; sub?: string; color: string; icon?: React.ElementType;
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

export default function CompetitionPanel({ status, agentStatus }: Props) {
  if (!status) return null;

  const ddColor =
    status.drawdown_pct < 8  ? "text-profit" :
    status.drawdown_pct < 15 ? "text-amber-400" :
    status.drawdown_pct < 22 ? "text-orange-400" : "text-loss";

  const tradesToday = status.trades_today;
  const todayColor  = status.min_trades_met ? "text-profit" : "text-amber-400";
  const zone        = status.drawdown_zone ?? "GREEN";
  const compass     = agentStatus?.compass;

  return (
    <Card className={cn(status.drawdown_halt && "border-loss/40")}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-1.5">
            <Shield size={12} className="text-accent" />
            Competition
          </CardTitle>
          <div className="flex items-center gap-2">
            {/* Drawdown zone badge */}
            {zone !== "GREEN" && (
              <span className={cn(
                "text-[9px] font-bold px-1.5 py-0.5 rounded border",
                ZONE_COLORS[zone] ?? "text-text-muted",
              )}>
                {zone}
              </span>
            )}
            {status.in_trading_window ? (
              <span className="badge-live text-[10px]">LIVE</span>
            ) : (
              <span className="text-[10px] text-text-muted font-medium">Jun 22–28</span>
            )}
          </div>
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

        {/* Zone warning (non-green, non-halt) */}
        {!status.drawdown_halt && zone !== "GREEN" && status.drawdown_zone_label && (
          <div className={cn(
            "flex items-center gap-2 px-3 py-2 rounded-xl border text-[11px] font-medium",
            ZONE_COLORS[zone] ?? "",
          )}>
            <TrendingDown size={11} />
            {status.drawdown_zone_label}
          </div>
        )}

        {/* Compass bar (if available) */}
        {compass && (
          <CompassBar score={compass.compass_score} regime={compass.regime} />
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
            value={status.in_trading_window ? `${tradesToday} trade${tradesToday !== 1 ? "s" : ""}` : "—"}
            sub={
              !status.in_trading_window ? "window not open" :
              status.min_trades_met ? "✓ min met" : "⚠ need 1 trade"
            }
            color={!status.in_trading_window ? "text-text-muted" : todayColor}
            icon={BarChart2}
          />

          {/* Today P&L */}
          <Metric
            label="Today PnL"
            value={
              !status.in_trading_window ? "—" :
              `${status.today_pnl >= 0 ? "+" : ""}$${status.today_pnl.toFixed(2)}`
            }
            sub={!status.in_trading_window ? "starts Jun 22" : undefined}
            color={
              !status.in_trading_window ? "text-text-muted" :
              status.today_pnl >= 0 ? "text-profit" : "text-loss"
            }
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
