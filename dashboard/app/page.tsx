"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { CheckCircle2, AlertTriangle, Info, X, RefreshCw } from "lucide-react";
import Header from "@/components/Header";
import StatsRow from "@/components/StatsRow";
import LatestStrategy from "@/components/LatestStrategy";
import TradeHistory from "@/components/TradeHistory";
import AgentRuns from "@/components/AgentRuns";
import ActivityFeed from "@/components/ActivityFeed";
import AdminPanel from "@/components/AdminPanel";
import OpenPositions from "@/components/OpenPositions";
import EquityCurve from "@/components/EquityCurve";
import LiveChart from "@/components/LiveChart";
import CompetitionPanel from "@/components/CompetitionPanel";
import TokenScannerPanel from "@/components/TokenScannerPanel";
import TwakStatusCard from "@/components/TwakStatusCard";
import GatesPanel from "@/components/GatesPanel";
import BotStatusBar from "@/components/BotStatusBar";
import type { Health, AgentStatus, Trade, Strategy, AgentRun, RunResult, CompetitionStatus, ActivityItem, BotConfig, TwakStatus } from "@/types";

type Notification = {
  id: number;
  type: "success" | "error" | "info";
  title: string;
  message: string;
};

let notifId = 0;

function NotificationToast({ notif, onDismiss }: { notif: Notification; onDismiss: () => void }) {
  const Icon = notif.type === "success" ? CheckCircle2 : notif.type === "error" ? AlertTriangle : Info;
  const styles = {
    success: "text-profit border-profit/25 bg-profit/10",
    error:   "text-loss border-loss/25 bg-loss/10",
    info:    "text-accent border-accent/25 bg-accent/10",
  }[notif.type];

  useEffect(() => {
    const t = setTimeout(onDismiss, 6000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  return (
    <div className={`flex items-start gap-3 px-4 py-3 rounded-2xl border text-sm animate-slide-in backdrop-blur-sm ${styles}`}>
      <Icon size={15} className="mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="font-semibold leading-tight">{notif.title}</p>
        <p className="opacity-75 text-xs mt-0.5 leading-snug">{notif.message}</p>
      </div>
      <button onClick={onDismiss} className="opacity-50 hover:opacity-100 transition-opacity shrink-0 mt-0.5">
        <X size={13} />
      </button>
    </div>
  );
}

export default function Dashboard() {
  const [health, setHealth]         = useState<Health | null>(null);
  const [status, setStatus]         = useState<AgentStatus | null>(null);
  const [trades, setTrades]         = useState<Trade[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [runs, setRuns]             = useState<AgentRun[]>([]);
  const [activity, setActivity]     = useState<ActivityItem[]>([]);
  const [botConfig, setBotConfig]   = useState<BotConfig | null>(null);
  const [competition, setCompetition] = useState<CompetitionStatus | null>(null);
  const [twakStatus, setTwakStatus]   = useState<TwakStatus | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [running, setRunning]       = useState(false);
  const [monitoring, setMonitoring] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const prevSnapshot = useRef<{
    latestRunId: number | null;
    latestRunError: string | null;
    failedTradeCount: number;
    minTradesMet: boolean | null;
  }>({ latestRunId: null, latestRunError: null, failedTradeCount: 0, minTradesMet: null });

  const addNotif = useCallback((type: Notification["type"], title: string, message: string) => {
    const id = ++notifId;
    setNotifications((prev) => [...prev, { id, type, title, message }]);
  }, []);

  const removeNotif = useCallback((id: number) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const fetchTokenPrice = useCallback(async (symbol: string): Promise<number | null> => {
    try {
      const res = await fetch(
        `https://api.binance.com/api/v3/ticker/price?symbol=${symbol.toUpperCase()}USDT`
      );
      if (!res.ok) return null;
      const data = await res.json();
      const price = parseFloat(data.price);
      return Number.isFinite(price) ? price : null;
    } catch {
      return null;
    }
  }, []);

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setRefreshing(true);
    try {
      const [h, s, t, st, r, comp, act, cfg, twak] = await Promise.allSettled([
        fetch("/api/proxy/health").then((r) => r.json()),
        fetch("/api/proxy/status").then((r) => r.json()),
        fetch("/api/proxy/trades?limit=50").then((r) => r.json()),
        fetch("/api/proxy/strategies?limit=20").then((r) => r.json()),
        fetch("/api/proxy/runs?limit=20").then((r) => r.json()),
        fetch("/api/proxy/competition").then((r) => r.json()),
        fetch("/api/proxy/activity?limit=20").then((r) => r.json()),
        fetch("/api/proxy/admin/config").then((r) => r.json()),
        fetch("/api/proxy/twak").then((r) => r.json()),
      ]);

      let tradesList: Trade[] = [];
      if (t.status === "fulfilled") {
        tradesList = (t.value as { trades: Trade[] }).trades ?? [];
        setTrades(tradesList);
      }

      const open = tradesList.find(
        (tr) =>
          tr.action === "BUY" &&
          tr.closed_at === null &&
          (tr.status === "dry_run" || tr.status === "executed")
      );
      if (open?.symbol) {
        const px = await fetchTokenPrice(open.symbol);
        setPositionPrice(px);
      } else {
        setPositionPrice(null);
      }

      if (h.status   === "fulfilled") setHealth(h.value as Health);
      if (s.status   === "fulfilled") setStatus(s.value as AgentStatus);
      if (st.status  === "fulfilled") setStrategies((st.value as { strategies: Strategy[] }).strategies ?? []);
      if (r.status   === "fulfilled") setRuns((r.value as { runs: AgentRun[] }).runs ?? []);
      if (comp.status === "fulfilled" && !(comp.value as { error?: string }).error)
        setCompetition(comp.value as CompetitionStatus);
      if (act.status === "fulfilled") setActivity((act.value as { items: ActivityItem[] }).items ?? []);
      if (cfg.status === "fulfilled" && !(cfg.value as { error?: string }).error)
        setBotConfig(cfg.value as BotConfig);
      if (twak.status === "fulfilled" && !(twak.value as { error?: string }).error)
        setTwakStatus(twak.value as TwakStatus);

      // Auto-alert on meaningful state changes (silent refresh only)
      if (silent) {
        const latestRun = (r.status === "fulfilled"
          ? (r.value as { runs: AgentRun[] }).runs?.[0]
          : null) ?? null;
        const failedCount = tradesList.filter((t) => t.status === "failed").length;
        const compData = comp.status === "fulfilled" && !(comp.value as { error?: string }).error
          ? (comp.value as CompetitionStatus)
          : null;
        const prev = prevSnapshot.current;

        if (latestRun && prev.latestRunId !== null && latestRun.id !== prev.latestRunId) {
          if (latestRun.error_message && !latestRun.error_message.startsWith("skip:")) {
            addNotif("error", `Run #${latestRun.id} failed`,
              latestRun.error_message.slice(0, 120));
          } else if (latestRun.trades_executed > 0) {
            addNotif("success", `Run #${latestRun.id} traded`,
              `${latestRun.trades_executed} swap(s) executed`);
          } else if (latestRun.error_message?.startsWith("skip:")) {
            const reason = latestRun.error_message.split(":")[1]?.replace(/_/g, " ") ?? "skipped";
            addNotif("info", `Run #${latestRun.id} skipped`, reason);
          }
        }

        if (failedCount > prev.failedTradeCount && prev.failedTradeCount > 0) {
          addNotif("error", "Swap failed",
            `${failedCount - prev.failedTradeCount} new failed trade(s) — check Trade History`);
        }

        if (compData && prev.minTradesMet === true && !compData.min_trades_met) {
          addNotif("info", "New UTC day", "Daily trade quota reset — bot will force trade if needed");
        }

        prevSnapshot.current = {
          latestRunId: latestRun?.id ?? prev.latestRunId,
          latestRunError: latestRun?.error_message ?? null,
          failedTradeCount: failedCount,
          minTradesMet: compData?.min_trades_met ?? prev.minTradesMet,
        };
      } else if (r.status === "fulfilled") {
        const latestRun = (r.value as { runs: AgentRun[] }).runs?.[0] ?? null;
        prevSnapshot.current = {
          latestRunId: latestRun?.id ?? null,
          latestRunError: latestRun?.error_message ?? null,
          failedTradeCount: tradesList.filter((t) => t.status === "failed").length,
          minTradesMet: comp.status === "fulfilled"
            ? (comp.value as CompetitionStatus).min_trades_met ?? null
            : null,
        };
      }

      setLastRefresh(new Date());
    } catch { /* silently fail — UI shows stale data */ } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [fetchTokenPrice]);

  const handleMonitor = useCallback(async () => {
    setMonitoring(true);
    try {
      const res    = await fetch("/api/proxy/monitor", { method: "POST" });
      const result = await res.json();
      if (result.closed > 0) {
        addNotif("success", "Positions checked", `${result.closed} trade(s) closed`);
      } else {
        addNotif("info", "Positions checked", `${result.checked} open · no TP/SL hit`);
      }
      await fetchAll(true);
    } catch (err) {
      addNotif("error", "Monitor failed", String(err));
    } finally {
      setMonitoring(false);
    }
  }, [fetchAll, addNotif]);

  const handleRunNow = useCallback(async () => {
    setRunning(true);
    try {
      const res    = await fetch("/api/proxy/run", { method: "POST" });
      const result: RunResult = await res.json();
      if (result.status === "executed") {
        addNotif("success", "Cycle executed",
          result.backtest ? `${result.action} · ${result.backtest.split("|")[0].trim()}` :
          `Trade ${result.trade_id ? `#${result.trade_id}` : ""} recorded`);
      } else if (result.status === "skipped") {
        addNotif("info", "Cycle skipped", result.reason ?? "No actionable signal");
      } else {
        addNotif("error", "Cycle error", result.error ?? "Unknown error");
      }
      await fetchAll(true);
    } catch (err) {
      addNotif("error", "Request failed", String(err));
    } finally {
      setRunning(false);
    }
  }, [fetchAll, addNotif]);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(() => fetchAll(true), 30_000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const hasClosedTrades = trades.some((t) => t.pnl_usd != null && t.closed_at != null);
  const initialPortfolio = competition?.initial_portfolio_usd ?? 1000;

  const openTrade = useMemo(
    () =>
      trades.find(
        (t) =>
          t.action === "BUY" &&
          t.closed_at === null &&
          (t.status === "dry_run" || t.status === "executed")
      ),
    [trades]
  );

  const [positionPrice, setPositionPrice] = useState<number | null>(null);

  useEffect(() => {
    const sym = openTrade?.symbol;
    if (!sym) return;
    const id = setInterval(() => {
      fetchTokenPrice(sym).then((px) => {
        if (px != null) setPositionPrice(px);
      });
    }, 5_000);
    return () => clearInterval(id);
  }, [openTrade?.symbol, fetchTokenPrice]);

  // Never fall back to BNB when an open position exists — causes a 1-frame PnL flash
  const markPrice = openTrade ? positionPrice : (health?.bnb_price ?? null);
  const markPair = openTrade
    ? `${openTrade.symbol}/USDT`
    : "BNB/USDT";

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="flex flex-col items-center gap-4 text-text-muted">
          <div className="w-10 h-10 rounded-2xl bg-profit/10 border border-profit/20 flex items-center justify-center">
            <RefreshCw size={18} className="animate-spin text-profit" />
          </div>
          <p className="text-sm font-medium">Connecting to AlphaLoop…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <Header
        health={health}
        status={status}
        lastRefresh={lastRefresh}
        running={running}
        monitoring={monitoring}
        onRunNow={handleRunNow}
        onMonitor={handleMonitor}
        livePair={markPair}
        livePrice={markPrice}
      />

      {/* Toast notifications */}
      {notifications.length > 0 && (
        <div className="fixed top-16 right-4 z-50 w-80 space-y-2 pointer-events-none">
          {notifications.map((n) => (
            <div key={n.id} className="pointer-events-auto">
              <NotificationToast notif={n} onDismiss={() => removeNotif(n.id)} />
            </div>
          ))}
        </div>
      )}

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-5">

        {/* Refresh pill */}
        {refreshing && (
          <div className="flex items-center gap-1.5 text-[11px] text-text-muted animate-fade-in">
            <RefreshCw size={10} className="animate-spin" />
            Refreshing…
          </div>
        )}

        {/* ── Bot status banner ─────────────────────────────────────────── */}
        <BotStatusBar
          status={status}
          competition={competition}
          runs={runs}
          paused={botConfig?.paused ?? false}
          backendOk={health?.status === "ok"}
        />

        {/* ── Row 1: Stats ─────────────────────────────────────────────── */}
        <StatsRow
          trades={trades}
          runs={runs}
          initialPortfolio={initialPortfolio}
          currentPrice={markPrice}
        />

        {/* ── Row 2: Activity + Competition + Gates ────────────────────── */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <div className="xl:col-span-2">
            <ActivityFeed items={activity} />
          </div>
          <div className="space-y-5">
            {competition && <CompetitionPanel status={competition} agentStatus={status} />}
            <GatesPanel competitionMode={status?.competition_mode ?? false} />
            <TwakStatusCard status={twakStatus} />
            <TokenScannerPanel competitionMode={status?.competition_mode ?? false} />
          </div>
        </div>

        {/* ── Row 3: Live Chart ─────────────────────────────────────────── */}
        <LiveChart trades={trades} strategies={strategies} />

        {/* ── Row 4: Open Positions + Equity Curve ─────────────────────── */}
        {hasClosedTrades ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <EquityCurve trades={trades} />
            <OpenPositions
              trades={trades}
              strategies={strategies}
              currentPrice={markPrice}
            />
          </div>
        ) : (
          <OpenPositions
            trades={trades}
            strategies={strategies}
            currentPrice={markPrice}
          />
        )}

        {/* ── Row 5: Latest Strategy ───────────────────────────────────── */}
        <LatestStrategy strategy={strategies[0]} />

        {/* ── Row 6: Trade History + Agent Runs ────────────────────────── */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <div className="xl:col-span-2">
            <TradeHistory trades={trades} />
          </div>
          <div>
            <AgentRuns runs={runs} />
          </div>
        </div>

      </main>

      {/* Footer */}
      <footer className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5 border-t border-border-subtle mt-4">
        <div className="flex items-center justify-between text-[11px] text-text-muted">
          <span className="font-medium">AlphaLoop · BSC · Auto-refresh 30s</span>
          <span className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full ${health?.status === "ok" ? "bg-profit animate-pulse" : "bg-loss"}`} />
            Backend {health?.status === "ok" ? "online" : "offline"}
          </span>
        </div>
      </footer>

      <AdminPanel config={botConfig} onUpdate={() => fetchAll(true)} />
    </div>
  );
}
