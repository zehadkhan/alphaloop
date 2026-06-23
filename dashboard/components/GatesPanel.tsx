"use client";

import { useEffect, useState } from "react";
import { CheckCircle, XCircle, AlertCircle, RefreshCw, Shield, TrendingUp, TrendingDown, Ban } from "lucide-react";

type GateData = {
  gates: {
    fear_greed: { value: number; label: string; pass: boolean; reason: string | null };
    btc_trend:  { change_80h: number; above_sma10: boolean; uptrend: boolean; pass: boolean; reason: string | null };
    token_7d:   { note: string; threshold: number };
  };
  all_pass:  boolean;
  blacklist: string[];
  compass:   string | null;
};

function fgColor(val: number) {
  if (val <= 25)  return "text-loss";
  if (val <= 45)  return "text-orange-400";
  if (val <= 55)  return "text-yellow-400";
  if (val <= 75)  return "text-profit";
  return "text-red-400";
}

function fgBar(val: number) {
  if (val <= 25)  return "bg-loss";
  if (val <= 45)  return "bg-orange-400";
  if (val <= 55)  return "bg-yellow-400";
  if (val <= 75)  return "bg-profit";
  return "bg-red-400";
}

export default function GatesPanel() {
  const [data, setData]       = useState<GateData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string>("");

  const fetchGates = async () => {
    try {
      const res = await fetch("/api/proxy/gates");
      if (res.ok) {
        setData(await res.json());
        setLastUpdated(new Date().toLocaleTimeString());
      }
    } catch {}
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchGates();
    const t = setInterval(fetchGates, 60_000); // refresh every minute
    return () => clearInterval(t);
  }, []);

  if (loading) return (
    <div className="rounded-2xl border border-border-subtle bg-surface p-5 animate-pulse h-48" />
  );
  if (!data) return null;

  const { gates, all_pass, blacklist, compass } = data;
  const fg  = gates.fear_greed;
  const btc = gates.btc_trend;

  return (
    <div className="rounded-2xl border border-border-subtle bg-surface p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield size={15} className="text-accent" />
          <h3 className="text-sm font-semibold text-text-primary">Trade Gates</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-text-muted">{lastUpdated}</span>
          <button onClick={fetchGates} className="p-1 rounded hover:bg-surface-2 text-text-muted hover:text-text-primary">
            <RefreshCw size={11} />
          </button>
          {all_pass ? (
            <span className="flex items-center gap-1 text-[10px] font-bold text-profit bg-profit/10 border border-profit/20 px-2 py-0.5 rounded-full">
              <CheckCircle size={10} /> TRADE ALLOWED
            </span>
          ) : (
            <span className="flex items-center gap-1 text-[10px] font-bold text-loss bg-loss/10 border border-loss/20 px-2 py-0.5 rounded-full">
              <XCircle size={10} /> BLOCKED
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">

        {/* Gate 1: Fear & Greed */}
        <div className={`rounded-xl border p-3 ${fg.pass ? "border-border-subtle bg-surface-2" : "border-loss/40 bg-loss/5"}`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">Fear & Greed</span>
            {fg.pass
              ? <CheckCircle size={13} className="text-profit" />
              : <XCircle    size={13} className="text-loss"   />}
          </div>
          <div className={`text-2xl font-bold tabular-nums ${fgColor(fg.value)}`}>
            {fg.value}<span className="text-sm font-normal text-text-muted">/100</span>
          </div>
          <div className="mt-2 h-1.5 rounded-full bg-surface-3 overflow-hidden">
            <div className={`h-full rounded-full transition-all ${fgBar(fg.value)}`} style={{ width: `${fg.value}%` }} />
          </div>
          <p className="mt-1.5 text-[10px] text-text-muted">{fg.label}</p>
          {!fg.pass && fg.reason && (
            <p className="mt-1 text-[10px] text-loss font-medium">⚠ {fg.reason}</p>
          )}
          <p className="mt-1 text-[10px] text-text-muted opacity-60">Pass zone: 25–85</p>
        </div>

        {/* Gate 2: BTC Trend */}
        <div className={`rounded-xl border p-3 ${btc.pass ? "border-border-subtle bg-surface-2" : "border-loss/40 bg-loss/5"}`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">BTC Trend (80h)</span>
            {btc.pass
              ? <CheckCircle size={13} className="text-profit" />
              : <XCircle    size={13} className="text-loss"   />}
          </div>
          <div className={`text-2xl font-bold tabular-nums ${btc.change_80h >= 0 ? "text-profit" : "text-loss"}`}>
            {btc.change_80h >= 0 ? "+" : ""}{btc.change_80h.toFixed(1)}
            <span className="text-sm font-normal text-text-muted">%</span>
          </div>
          <div className="flex items-center gap-1.5 mt-2">
            {btc.uptrend
              ? <TrendingUp  size={13} className="text-profit" />
              : <TrendingDown size={13} className="text-loss"  />}
            <span className={`text-[11px] font-medium ${btc.uptrend ? "text-profit" : "text-loss"}`}>
              {btc.uptrend ? "Uptrend" : "Downtrend"}
            </span>
            <span className="text-[10px] text-text-muted">
              · SMA10 {btc.above_sma10 ? "above ✓" : "below ✗"}
            </span>
          </div>
          {!btc.pass && btc.reason && (
            <p className="mt-1.5 text-[10px] text-loss font-medium">⚠ {btc.reason}</p>
          )}
        </div>

        {/* Gate 3: Token 7d */}
        <div className="rounded-xl border border-border-subtle bg-surface-2 p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">Token 7-Day Filter</span>
            <AlertCircle size={13} className="text-accent" />
          </div>
          <p className="text-[11px] text-text-primary font-medium">Checked per cycle</p>
          <p className="text-[10px] text-text-muted mt-1">
            Tokens down &gt;20% in 7 days are skipped automatically
          </p>
        </div>

        {/* Compass */}
        <div className="rounded-xl border border-border-subtle bg-surface-2 p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">Market Regime</span>
          </div>
          <p className={`text-sm font-bold ${
            compass === "BULL_TREND" ? "text-profit"
            : compass === "RISK_OFF" ? "text-loss"
            : "text-yellow-400"
          }`}>
            {compass ?? "—"}
          </p>
          <p className="text-[10px] text-text-muted mt-1">From 5-Axis Compass</p>
        </div>
      </div>

      {/* Blacklist */}
      {blacklist.length > 0 && (
        <div className="rounded-xl border border-border-subtle bg-surface-2 p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <Ban size={11} className="text-loss" />
            <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">
              Token Blacklist ({blacklist.length})
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {blacklist.map(t => (
              <span key={t} className="text-[10px] font-mono bg-loss/10 text-loss border border-loss/20 px-1.5 py-0.5 rounded">
                {t}
              </span>
            ))}
          </div>
          <p className="mt-1.5 text-[10px] text-text-muted">
            Auto-blacklisted — TWAK cannot route these tokens
          </p>
        </div>
      )}
    </div>
  );
}
