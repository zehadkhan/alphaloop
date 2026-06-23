"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  PauseCircle,
  ShieldAlert,
  TrendingDown,
  Zap,
} from "lucide-react";
import { timeUntil } from "@/lib/utils";
import type { AgentRun, AgentStatus, CompetitionStatus } from "@/types";

type GateSnapshot = {
  fear_greed: { value: number; label: string; pass: boolean };
  btc_trend: { uptrend: boolean; change_80h: number; pass: boolean };
  blacklist: string[];
};

type Props = {
  status: AgentStatus | null;
  competition: CompetitionStatus | null;
  runs: AgentRun[];
  paused?: boolean;
  backendOk?: boolean;
};

type BannerTone = "ok" | "warn" | "error" | "info";

function parseSkip(msg: string | null): string | null {
  if (!msg?.startsWith("skip:")) return null;
  const key = msg.split(":")[1] ?? "";
  const map: Record<string, string> = {
    extreme_fear: "Extreme Fear gate (legacy skip)",
    extreme_greed: "Extreme Greed gate",
    btc_downtrend: "BTC downtrend — waiting for recovery",
    token_weak_7d: "Token too weak (7d)",
    unroutable_token: "Token not routable on TWAK",
    HOLD: "Claude said HOLD",
    low_confidence: "Confidence too low",
    backtest_failed: "Backtest failed",
    risk_off_regime: "Risk-off regime",
    edge_gate_failed: "Expected edge below fees",
    swap_failed: "Swap failed on-chain",
    max_positions_reached: "Max positions full",
    token_already_held: "Already holding token",
    drawdown_halt: "Drawdown halt",
    daily_loss_limit: "Daily loss limit hit",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function deriveState(
  status: AgentStatus | null,
  competition: CompetitionStatus | null,
  runs: AgentRun[],
  gates: GateSnapshot | null,
  paused: boolean,
  backendOk: boolean,
): { tone: BannerTone; headline: string; sub: string; hints: string[] } {
  const hints: string[] = [];
  const latest = runs[0] ?? status?.last_run ?? null;
  const nextCycle = status?.scheduled_jobs?.find((j) => j.id === "agent_cycle")?.next_run;

  if (!backendOk) {
    return {
      tone: "error",
      headline: "Backend offline",
      sub: "Cannot reach the agent API — data may be stale.",
      hints: ["Check Coolify alphaloop service is running"],
    };
  }

  if (paused) {
    return {
      tone: "warn",
      headline: "Bot paused",
      sub: "Admin paused trading — cycles will not execute until resumed.",
      hints: ["Open Admin panel to resume"],
    };
  }

  if (competition?.drawdown_halt) {
    return {
      tone: "error",
      headline: "Trading halted — drawdown limit",
      sub: `Drawdown ${competition.drawdown_pct.toFixed(1)}% — bot stopped to protect capital.`,
      hints: ["Review trade history and wait for manual reset or recovery"],
    };
  }

  if (gates && gates.fear_greed.value < 25 && competition?.competition_mode) {
    hints.push(`Extreme Fear (F&G ${gates.fear_greed.value}) — trades use 50% size, not skipped`);
  }
  if (gates && !gates.btc_trend.pass) {
    hints.push(`BTC 80h ${gates.btc_trend.change_80h >= 0 ? "+" : ""}${gates.btc_trend.change_80h.toFixed(1)}% — cycles may skip until uptrend`);
  }
  if (gates && gates.blacklist.length > 0) {
    hints.push(`${gates.blacklist.length} token(s) blacklisted (unroutable): ${gates.blacklist.slice(0, 4).join(", ")}${gates.blacklist.length > 4 ? "…" : ""}`);
  }

  if (competition?.in_trading_window) {
    if (competition.min_trades_met) {
      hints.push(`Daily quota met (${competition.trades_today} trade${competition.trades_today !== 1 ? "s" : ""} today)`);
    } else {
      hints.push(`Daily quota: ${competition.trades_today}/1 — bot will force a trade if still 0 near midnight UTC`);
    }
  }

  if (latest?.error_message && !latest.error_message.startsWith("skip:")) {
    const short = latest.error_message.length > 100
      ? latest.error_message.slice(0, 100) + "…"
      : latest.error_message;
    return {
      tone: "error",
      headline: `Last cycle failed — Run #${latest.id}`,
      sub: short,
      hints,
    };
  }

  const skip = parseSkip(latest?.error_message ?? null);
  if (skip) {
    return {
      tone: "warn",
      headline: `Last cycle skipped — Run #${latest?.id ?? "?"}`,
      sub: skip,
      hints: [...hints, nextCycle ? `Next cycle ${timeUntil(nextCycle)}` : ""].filter(Boolean),
    };
  }

  if (latest && latest.trades_executed > 0) {
    return {
      tone: "ok",
      headline: `Last cycle traded — Run #${latest.id}`,
      sub: `${latest.trades_executed} swap(s) executed · PnL ${latest.total_pnl >= 0 ? "+" : ""}$${latest.total_pnl.toFixed(2)}`,
      hints: [...hints, nextCycle ? `Next cycle ${timeUntil(nextCycle)}` : ""].filter(Boolean),
    };
  }

  if (latest && latest.strategies_generated > 0) {
    return {
      tone: "info",
      headline: `Watching market — Run #${latest.id}`,
      sub: "Claude analyzed but did not trade (HOLD / gates / low confidence).",
      hints: [...hints, nextCycle ? `Next cycle ${timeUntil(nextCycle)}` : ""].filter(Boolean),
    };
  }

  return {
    tone: "info",
    headline: "Bot is live",
    sub: nextCycle ? `Next automatic cycle ${timeUntil(nextCycle)}` : "Scheduler active",
    hints,
  };
}

const TONE_STYLES: Record<BannerTone, { bar: string; icon: string }> = {
  ok:    { bar: "border-profit/30 bg-profit/8",  icon: "text-profit" },
  warn:  { bar: "border-amber-500/30 bg-amber-500/8", icon: "text-amber-400" },
  error: { bar: "border-loss/30 bg-loss/8", icon: "text-loss" },
  info:  { bar: "border-accent/30 bg-accent/8", icon: "text-accent" },
};

const TONE_ICONS: Record<BannerTone, React.ElementType> = {
  ok: CheckCircle2,
  warn: ShieldAlert,
  error: AlertTriangle,
  info: Clock,
};

export default function BotStatusBar({ status, competition, runs, paused = false, backendOk = true }: Props) {
  const [gates, setGates] = useState<GateSnapshot | null>(null);

  useEffect(() => {
    fetch("/api/proxy/gates")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.gates) {
          setGates({
            fear_greed: d.gates.fear_greed,
            btc_trend: d.gates.btc_trend,
            blacklist: d.blacklist ?? [],
          });
        }
      })
      .catch(() => {});
    const id = setInterval(() => {
      fetch("/api/proxy/gates")
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (d?.gates) {
            setGates({
              fear_greed: d.gates.fear_greed,
              btc_trend: d.gates.btc_trend,
              blacklist: d.blacklist ?? [],
            });
          }
        })
        .catch(() => {});
    }, 60_000);
    return () => clearInterval(id);
  }, []);

  const { tone, headline, sub, hints } = deriveState(
    status, competition, runs, gates, paused, backendOk,
  );
  const styles = TONE_STYLES[tone];
  const Icon = TONE_ICONS[tone];

  return (
    <div className={`rounded-2xl border px-4 py-3 ${styles.bar}`}>
      <div className="flex items-start gap-3">
        <Icon size={18} className={`shrink-0 mt-0.5 ${styles.icon}`} />
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-text-primary">{headline}</p>
            {status?.compass?.regime && (
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-white/5 border border-border-subtle text-text-muted">
                {status.compass.regime}
              </span>
            )}
            {gates && (
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-white/5 border border-border-subtle text-text-muted">
                F&G {gates.fear_greed.value}
              </span>
            )}
            {competition?.in_trading_window && (
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                competition.min_trades_met
                  ? "bg-profit/10 text-profit border-profit/25"
                  : "bg-amber-500/10 text-amber-400 border-amber-500/25"
              }`}>
                {competition.min_trades_met ? "Daily ✓" : "Need 1 trade"}
              </span>
            )}
          </div>
          <p className="text-xs text-text-muted mt-0.5 leading-relaxed">{sub}</p>
          {hints.length > 0 && (
            <ul className="mt-2 space-y-1">
              {hints.map((h) => (
                <li key={h} className="text-[11px] text-text-secondary flex items-start gap-1.5">
                  <Zap size={10} className="shrink-0 mt-0.5 opacity-50" />
                  {h}
                </li>
              ))}
            </ul>
          )}
        </div>
        {paused && (
          <PauseCircle size={16} className="text-amber-400 shrink-0" />
        )}
        {!gates?.btc_trend.pass && tone !== "error" && (
          <TrendingDown size={16} className="text-amber-400 shrink-0 opacity-70" title="BTC downtrend" />
        )}
      </div>
    </div>
  );
}
