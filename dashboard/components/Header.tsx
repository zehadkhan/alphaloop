"use client";

import { RefreshCw, Zap, Activity, ScanLine } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import ThemeToggle from "@/components/ThemeToggle";
import { formatPrice, timeAgo, timeUntil } from "@/lib/utils";
import type { Health, AgentStatus } from "@/types";

type Props = {
  health: Health | null;
  status: AgentStatus | null;
  lastRefresh: Date;
  running: boolean;
  monitoring: boolean;
  onRunNow: () => void;
  onMonitor: () => void;
};

export default function Header({ health, status, lastRefresh, running, monitoring, onRunNow, onMonitor }: Props) {
  const isAlive = health?.status === "ok";
  const bnbPrice = health?.bnb_price;
  const isDryRun = status?.dry_run ?? true;
  const isTWAK = status?.signing_backend === "twak";
  const isCompetition = status?.competition_mode ?? false;
  const nextJob = status?.scheduled_jobs?.find((j) => j.id === "agent_cycle")?.next_run;
  const openPositions = status?.open_positions ?? 0;

  return (
    <header className="sticky top-0 z-40 border-b border-border-subtle bg-background/95 backdrop-blur-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        {/* Logo */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-profit/10 border border-profit/30">
            <Zap size={16} className="text-profit" />
          </div>
          <div className="flex items-baseline gap-0.5">
            <span className="text-lg font-bold text-text-primary">Alpha</span>
            <span className="text-lg font-bold text-profit">Loop</span>
          </div>
          {isDryRun && (
            <Badge variant="dry_run" className="text-[10px]">DRY RUN</Badge>
          )}
          {isTWAK && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border border-accent/40 text-accent font-semibold">TWAK</span>
          )}
          {isCompetition && !isDryRun && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border border-profit/40 text-profit font-semibold">LIVE</span>
          )}
        </div>

        {/* Center — BNB price + status */}
        <div className="flex items-center gap-5">
          {bnbPrice != null && (
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-profit opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-profit" />
              </span>
              <span className="text-xs text-text-muted font-medium">BNB/USDT</span>
              <span className="text-base font-bold text-text-primary tabular-nums">
                {formatPrice(bnbPrice)}
              </span>
            </div>
          )}

          <div className="hidden sm:flex items-center gap-1.5">
            <Activity size={12} className={isAlive ? "text-profit" : "text-loss"} />
            <span className="text-xs text-text-secondary">
              {isAlive ? "Agent online" : "Agent offline"}
            </span>
          </div>
        </div>

        {/* Right — refresh info + CTA */}
        <div className="flex items-center gap-3 shrink-0">
          <ThemeToggle />

        <div className="hidden md:flex flex-col items-end">
            <span className="text-[10px] text-text-muted">Last refresh</span>
            <span className="text-xs text-text-secondary tabular-nums">
              {timeAgo(lastRefresh.toISOString())}
            </span>
          </div>

          {nextJob && (
            <div className="hidden lg:flex flex-col items-end">
              <span className="text-[10px] text-text-muted">Next run</span>
              <span className="text-xs text-text-secondary tabular-nums">
                {timeUntil(nextJob)}
              </span>
            </div>
          )}

          {openPositions > 0 && (
            <button
              onClick={onMonitor}
              disabled={monitoring}
              title="Check open positions against TP/SL"
              className="hidden sm:flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-lg border border-border-subtle bg-surface-2 text-text-secondary hover:text-profit hover:border-profit/40 transition-all disabled:opacity-50"
            >
              {monitoring ? (
                <RefreshCw size={12} className="animate-spin" />
              ) : (
                <ScanLine size={12} />
              )}
              {openPositions} open
            </button>
          )}

          <Button
            variant="primary"
            size="md"
            onClick={onRunNow}
            disabled={running}
            className="gap-2"
          >
            {running ? (
              <>
                <RefreshCw size={14} className="animate-spin" />
                <span className="hidden sm:inline">Running…</span>
              </>
            ) : (
              <>
                <Zap size={14} />
                <span className="hidden sm:inline">Run Now</span>
              </>
            )}
          </Button>
        </div>
      </div>
    </header>
  );
}
