"use client";

import { Zap, Activity, ScanLine, RefreshCw, Radio } from "lucide-react";
import { Button } from "@/components/ui/button";
import ThemeToggle from "@/components/ThemeToggle";
import { formatPrice, timeAgo, timeUntil } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { Health, AgentStatus } from "@/types";

type Props = {
  health: Health | null;
  status: AgentStatus | null;
  lastRefresh: Date;
  running: boolean;
  monitoring: boolean;
  onRunNow: () => void;
  onMonitor: () => void;
  livePair?: string;
  livePrice?: number | null;
};

export default function Header({
  health,
  status,
  lastRefresh,
  running,
  monitoring,
  onRunNow,
  onMonitor,
  livePair,
  livePrice,
}: Props) {
  const isAlive = health?.status === "ok";
  const tickerPrice = livePrice ?? health?.bnb_price;
  const isDryRun = status?.dry_run ?? true;
  const isTWAK = status?.signing_backend === "twak";
  const isCompetition = status?.competition_mode ?? false;
  const isLive = isCompetition && !isDryRun;
  const nextJob = status?.scheduled_jobs?.find((j) => j.id === "agent_cycle")?.next_run;
  const openPositions = status?.open_positions ?? 0;
  const tradingPair = livePair ?? status?.trading_pair ?? "BNB/USDT";

  return (
    <header className="sticky top-0 z-40 border-b border-border-subtle bg-background/80 backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between gap-3">

        {/* ── Left: logo + mode badges ─────────────────────────────────── */}
        <div className="flex items-center gap-2.5 shrink-0">
          {/* Logo icon */}
          <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-profit/15 border border-profit/25">
            <Zap size={14} className="text-profit" strokeWidth={2.5} />
          </div>

          {/* Wordmark */}
          <div className="flex items-baseline gap-0">
            <span className="text-[15px] font-bold text-text-primary tracking-tight">Alpha</span>
            <span className="text-[15px] font-bold text-profit tracking-tight">Loop</span>
          </div>

          {/* Mode badges */}
          <div className="flex items-center gap-1.5">
            {isDryRun && (
              <span className="text-[10px] bg-amber-500/15 text-amber-400 border border-amber-500/25 px-2 py-0.5 rounded-full font-semibold leading-none">
                DRY RUN
              </span>
            )}

            {isTWAK && (
              <span className="text-[10px] bg-accent/15 text-accent border border-accent/25 px-2 py-0.5 rounded-full font-semibold leading-none">
                TWAK
              </span>
            )}

            {isLive && (
              <span className="inline-flex items-center gap-1 text-[10px] bg-profit/12 text-profit border border-profit/25 px-2 py-0.5 rounded-full font-semibold leading-none">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-profit opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-profit" />
                </span>
                LIVE
              </span>
            )}
          </div>
        </div>

        {/* ── Center: live price ticker + agent status ─────────────────── */}
        <div className="hidden md:flex items-center gap-4">
          {/* Price ticker */}
          {tickerPrice != null && (
            <div className="flex items-center gap-2">
              {/* Live pulse dot */}
              <span className="relative flex h-2 w-2 shrink-0">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-profit opacity-70" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-profit" />
              </span>

              {/* Pair label */}
              <span className="text-xs text-text-muted font-medium tabular-nums">
                {tradingPair}
              </span>

              {/* Price value */}
              <span className="text-base font-bold text-text-primary font-mono tabular-nums">
                {formatPrice(tickerPrice)}
              </span>
            </div>
          )}

          {/* Divider */}
          {tickerPrice != null && (
            <div className="h-4 w-px bg-border-subtle" />
          )}

          {/* Agent online/offline */}
          <div className="flex items-center gap-1.5">
            <Activity
              size={12}
              strokeWidth={2}
              className={isAlive ? "text-profit" : "text-loss"}
            />
            <span
              className={cn(
                "text-xs font-medium",
                isAlive ? "text-text-secondary" : "text-loss/80"
              )}
            >
              {isAlive ? "Agent online" : "Agent offline"}
            </span>
          </div>
        </div>

        {/* ── Right: controls ───────────────────────────────────────────── */}
        <div className="flex items-center gap-2 shrink-0">
          <ThemeToggle />

          {/* Last refresh — hidden on small screens */}
          <div className="hidden md:flex flex-col items-end min-w-[64px]">
            <span className="text-[10px] text-text-muted leading-tight">Last refresh</span>
            <span className="text-[11px] text-text-secondary tabular-nums leading-tight font-medium">
              {timeAgo(lastRefresh.toISOString())}
            </span>
          </div>

          {/* Next run — hidden on medium screens */}
          {nextJob && (
            <div className="hidden lg:flex flex-col items-end min-w-[56px]">
              <span className="text-[10px] text-text-muted leading-tight">Next run</span>
              <span className="text-[11px] text-text-secondary tabular-nums leading-tight font-medium">
                {timeUntil(nextJob)}
              </span>
            </div>
          )}

          {/* Monitor open positions button */}
          {openPositions > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onMonitor}
              disabled={monitoring}
              title="Check open positions against TP/SL"
              className="hidden sm:inline-flex"
            >
              {monitoring ? (
                <RefreshCw size={12} className="animate-spin" />
              ) : (
                <ScanLine size={12} />
              )}
              <span className="tabular-nums">{openPositions}</span>
            </Button>
          )}

          {/* Run Now CTA */}
          <Button
            variant="primary"
            size="md"
            onClick={onRunNow}
            disabled={running}
          >
            {running ? (
              <>
                <RefreshCw size={13} className="animate-spin" />
                <span className="hidden sm:inline">Running…</span>
              </>
            ) : (
              <>
                <Zap size={13} strokeWidth={2.5} />
                <span className="hidden sm:inline">Run Now</span>
              </>
            )}
          </Button>
        </div>

      </div>
    </header>
  );
}
