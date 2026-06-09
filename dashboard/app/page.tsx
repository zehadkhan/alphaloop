"use client";

import { useState, useEffect, useCallback } from "react";
import { CheckCircle2, AlertTriangle, Info, X, RefreshCw } from "lucide-react";
import Header from "@/components/Header";
import StatsRow from "@/components/StatsRow";
import LatestStrategy from "@/components/LatestStrategy";
import TradeHistory from "@/components/TradeHistory";
import AgentRuns from "@/components/AgentRuns";
import type { Health, AgentStatus, Trade, Strategy, AgentRun, RunResult } from "@/types";

type Notification = {
  id: number;
  type: "success" | "error" | "info";
  title: string;
  message: string;
};

let notifId = 0;

function NotificationToast({
  notif,
  onDismiss,
}: {
  notif: Notification;
  onDismiss: () => void;
}) {
  const Icon =
    notif.type === "success"
      ? CheckCircle2
      : notif.type === "error"
      ? AlertTriangle
      : Info;
  const color =
    notif.type === "success"
      ? "text-profit border-profit/30 bg-profit/10"
      : notif.type === "error"
      ? "text-loss border-loss/30 bg-loss/10"
      : "text-accent border-accent/30 bg-accent/10";

  useEffect(() => {
    const t = setTimeout(onDismiss, 6000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 rounded-xl border text-sm animate-slide-in ${color}`}
    >
      <Icon size={16} className="mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="font-semibold">{notif.title}</p>
        <p className="opacity-80 text-xs mt-0.5">{notif.message}</p>
      </div>
      <button onClick={onDismiss} className="opacity-60 hover:opacity-100 transition-opacity shrink-0">
        <X size={14} />
      </button>
    </div>
  );
}

export default function Dashboard() {
  const [health, setHealth] = useState<Health | null>(null);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [running, setRunning] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const addNotif = useCallback(
    (type: Notification["type"], title: string, message: string) => {
      const id = ++notifId;
      setNotifications((prev) => [...prev, { id, type, title, message }]);
    },
    []
  );

  const removeNotif = useCallback((id: number) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setRefreshing(true);
    try {
      const [h, s, t, st, r] = await Promise.allSettled([
        fetch("/api/proxy/health").then((r) => r.json()),
        fetch("/api/proxy/status").then((r) => r.json()),
        fetch("/api/proxy/trades?limit=50").then((r) => r.json()),
        fetch("/api/proxy/strategies?limit=20").then((r) => r.json()),
        fetch("/api/proxy/runs?limit=20").then((r) => r.json()),
      ]);

      if (h.status === "fulfilled") setHealth(h.value as Health);
      if (s.status === "fulfilled") setStatus(s.value as AgentStatus);
      if (t.status === "fulfilled") setTrades((t.value as { trades: Trade[] }).trades ?? []);
      if (st.status === "fulfilled") setStrategies((st.value as { strategies: Strategy[] }).strategies ?? []);
      if (r.status === "fulfilled") setRuns((r.value as { runs: AgentRun[] }).runs ?? []);

      setLastRefresh(new Date());
    } catch {
      // silently fail — UI will show stale data
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const handleRunNow = useCallback(async () => {
    setRunning(true);
    try {
      const res = await fetch("/api/proxy/run", { method: "POST" });
      const result: RunResult = await res.json();

      if (result.status === "executed") {
        addNotif(
          "success",
          "Cycle executed",
          result.backtest
            ? `${result.action} · ${result.backtest.split("|")[0].trim()}`
            : `Trade ${result.trade_id ? `#${result.trade_id}` : ""} recorded`
        );
      } else if (result.status === "skipped") {
        addNotif(
          "info",
          "Cycle skipped",
          result.reason ?? "No actionable signal"
        );
      } else {
        addNotif(
          "error",
          "Cycle error",
          result.error ?? "Unknown error"
        );
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

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="flex flex-col items-center gap-3 text-text-muted">
          <RefreshCw size={24} className="animate-spin text-profit" />
          <p className="text-sm">Connecting to AlphaLoop agent…</p>
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
        onRunNow={handleRunNow}
      />

      {/* Notifications */}
      {notifications.length > 0 && (
        <div className="fixed top-20 right-4 z-50 w-80 space-y-2">
          {notifications.map((n) => (
            <NotificationToast
              key={n.id}
              notif={n}
              onDismiss={() => removeNotif(n.id)}
            />
          ))}
        </div>
      )}

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Refresh indicator */}
        {refreshing && (
          <div className="flex items-center gap-1.5 text-xs text-text-muted animate-fade-in">
            <RefreshCw size={11} className="animate-spin" />
            Refreshing…
          </div>
        )}

        <StatsRow trades={trades} runs={runs} />

        <LatestStrategy strategy={strategies[0]} />

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <div className="xl:col-span-2">
            <TradeHistory trades={trades} />
          </div>
          <div>
            <AgentRuns runs={runs} />
          </div>
        </div>
      </main>

      <footer className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 border-t border-border-subtle">
        <div className="flex items-center justify-between text-xs text-text-muted">
          <span>AlphaLoop · BSC Testnet · Auto-refreshes every 30s</span>
          <span>
            Backend:{" "}
            <span
              className={health?.status === "ok" ? "text-profit" : "text-loss"}
            >
              {health?.status === "ok" ? "● online" : "● offline"}
            </span>
          </span>
        </div>
      </footer>
    </div>
  );
}
