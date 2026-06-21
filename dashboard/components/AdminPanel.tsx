"use client";

import { useState, useEffect } from "react";
import { Pause, Play, X, Save, AlertTriangle, Settings, Brain, DollarSign, Target, Zap, Timer, Lock } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { BotConfig } from "@/types";

const ALL_TOKENS = [
  "BNB", "BTC", "ETH", "SOL", "ADA", "DOT", "LINK", "UNI",
  "AAVE", "CAKE", "NEAR", "AVAX", "MATIC", "ATOM", "DOGE",
];

type Props = {
  config: BotConfig | null;
  onUpdate: () => void;
};

export default function AdminPanel({ config, onUpdate }: Props) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [closing, setClosing] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [saved, setSaved] = useState(false);
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState(false);

  const [posSize, setPosSize] = useState<number>(10);
  const [minConf, setMinConf] = useState<number>(60);
  const [instruction, setInstruction] = useState<string>("");
  const [tokens, setTokens] = useState<string[]>(["BNB"]);
  const [monitorInterval, setMonitorInterval] = useState<number>(2);

  useEffect(() => {
    if (config) {
      setPosSize(config.position_size_usd ?? 10);
      setMinConf(Math.round((config.min_confidence ?? 0.6) * 100));
      setInstruction(config.claude_instruction ?? "");
      setTokens(config.eligible_tokens ?? ["BNB"]);
      setMonitorInterval(config.monitor_interval_minutes ?? 2);
    }
  }, [config]);

  const adminHeaders = () => ({
    "Content-Type": "application/json",
    "x-admin-password": password,
  });

  const handleSave = async () => {
    setSaving(true);
    setAuthError(false);
    try {
      const res = await fetch("/api/proxy/admin/config", {
        method: "POST",
        headers: adminHeaders(),
        body: JSON.stringify({
          position_size_usd: posSize,
          min_confidence: minConf / 100,
          claude_instruction: instruction || null,
          monitor_interval_minutes: monitorInterval,
        }),
      });
      if (res.status === 401) { setAuthError(true); return; }
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      onUpdate();
    } finally {
      setSaving(false);
    }
  };

  const handleTogglePause = async () => {
    setToggling(true);
    setAuthError(false);
    try {
      const res = await fetch("/api/proxy/admin/pause", { method: "POST", headers: adminHeaders() });
      if (res.status === 401) { setAuthError(true); return; }
      onUpdate();
    } finally {
      setToggling(false);
    }
  };

  const handleCloseAll = async () => {
    if (!confirm("Close ALL open positions at current market price?")) return;
    setClosing(true);
    setAuthError(false);
    try {
      const res = await fetch("/api/proxy/admin/close-all", { method: "POST", headers: adminHeaders() });
      if (res.status === 401) { setAuthError(true); setClosing(false); return; }
      const data = await res.json();
      alert(`Closed ${data.closed} position(s).`);
      onUpdate();
    } finally {
      setClosing(false);
    }
  };

  const toggleToken = (t: string) => {
    setTokens((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]
    );
  };

  const isPaused = config?.paused ?? false;

  return (
    <>
      {/* Floating trigger button */}
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 px-4 py-2.5 rounded-full bg-surface-2 border border-border-subtle text-sm font-medium text-text-primary hover:bg-surface-3 shadow-lg transition-all"
      >
        <Settings size={15} />
        Admin
        {isPaused && (
          <span className="ml-1 px-1.5 py-0.5 text-xs bg-loss/20 text-loss rounded-full font-semibold">
            PAUSED
          </span>
        )}
      </button>

      {/* Slide-over panel */}
      {open && (
        <div className="fixed inset-0 z-50 flex justify-end">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setOpen(false)}
          />

          {/* Panel */}
          <div className="relative w-full max-w-md bg-background border-l border-border-subtle overflow-y-auto flex flex-col shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-border-subtle sticky top-0 bg-background z-10">
              <div className="flex items-center gap-2">
                <Settings size={16} className="text-accent" />
                <h2 className="text-base font-semibold text-text-primary">Bot Controls</h2>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="p-1.5 rounded-lg hover:bg-surface-2 text-text-muted hover:text-text-primary transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <div className="flex-1 px-6 py-5 space-y-6">

              {/* Password */}
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <Lock size={12} /> Admin Password
                </h3>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setAuthError(false); }}
                  placeholder="Enter admin password"
                  className={`w-full px-3 py-2.5 text-sm bg-surface-2 border rounded-xl text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 ${
                    authError ? "border-loss focus:ring-loss/50" : "border-border-subtle focus:ring-accent/50"
                  }`}
                />
                {authError && (
                  <p className="mt-1.5 text-xs text-loss font-medium">Incorrect password</p>
                )}
              </section>

              {/* Pause / Resume */}
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
                  Bot State
                </h3>
                <button
                  onClick={handleTogglePause}
                  disabled={toggling}
                  className={`w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm transition-all ${
                    isPaused
                      ? "bg-profit/15 text-profit border border-profit/30 hover:bg-profit/25"
                      : "bg-loss/15 text-loss border border-loss/30 hover:bg-loss/25"
                  }`}
                >
                  {isPaused ? <Play size={16} /> : <Pause size={16} />}
                  {toggling ? "Updating…" : isPaused ? "Resume Bot" : "Pause Bot"}
                </button>
                {isPaused && (
                  <p className="mt-2 text-xs text-loss text-center">
                    Bot is paused — no new trades will open
                  </p>
                )}
              </section>

              {/* Position Size */}
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <DollarSign size={12} /> Position Size per Trade
                </h3>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={1}
                    max={50}
                    step={0.5}
                    value={posSize}
                    onChange={(e) => setPosSize(Number(e.target.value))}
                    className="flex-1 accent-accent"
                  />
                  <span className="text-sm font-semibold text-text-primary w-14 text-right">
                    ${posSize.toFixed(1)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-text-muted">
                  Max loss per trade ≈ ${(posSize * 0.041).toFixed(2)} (4.1% SL)
                </p>
              </section>

              {/* Min Confidence */}
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <Target size={12} /> Min Confidence to Trade
                </h3>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={40}
                    max={90}
                    step={5}
                    value={minConf}
                    onChange={(e) => setMinConf(Number(e.target.value))}
                    className="flex-1 accent-accent"
                  />
                  <span className="text-sm font-semibold text-text-primary w-14 text-right">
                    {minConf}%
                  </span>
                </div>
                <p className="mt-1 text-xs text-text-muted">
                  {minConf <= 55
                    ? "More trades, higher risk"
                    : minConf >= 75
                    ? "Fewer trades, more selective"
                    : "Balanced — recommended"}
                </p>
              </section>

              {/* Monitor Interval */}
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <Timer size={12} /> Price Check Interval
                </h3>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={1}
                    max={10}
                    step={1}
                    value={monitorInterval}
                    onChange={(e) => setMonitorInterval(Number(e.target.value))}
                    className="flex-1 accent-accent"
                  />
                  <span className="text-sm font-semibold text-text-primary w-16 text-right">
                    {monitorInterval} min
                  </span>
                </div>
                <p className="mt-1 text-xs text-text-muted">
                  {monitorInterval === 1
                    ? "Every minute — fastest response to price drops"
                    : monitorInterval <= 3
                    ? `Every ${monitorInterval} min — good balance`
                    : `Every ${monitorInterval} min — slower but less API usage`}
                </p>
              </section>

              {/* Claude Instruction */}
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <Brain size={12} /> Instruction to Claude
                </h3>
                <textarea
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                  placeholder="e.g. Be conservative today. Only BUY if RSI is below 40 and the 4h trend is bullish."
                  rows={4}
                  className="w-full px-3 py-2.5 text-xs bg-surface-2 border border-border-subtle rounded-xl text-text-primary placeholder:text-text-muted resize-none focus:outline-none focus:ring-1 focus:ring-accent/50"
                />
                <p className="mt-1 text-xs text-text-muted">
                  Claude will follow this in the next cycle
                </p>
              </section>

              {/* Token Selection */}
              <section>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <Zap size={12} /> Active Tokens
                </h3>
                <p className="text-xs text-text-muted">
                  149 tokens configured in backend — managed via config, not overridable here.
                </p>
              </section>

              {/* Save button */}
              <button
                onClick={handleSave}
                disabled={saving}
                className={`w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm transition-all ${
                  saved
                    ? "bg-profit/20 text-profit border border-profit/30"
                    : "bg-accent/15 text-accent border border-accent/30 hover:bg-accent/25"
                }`}
              >
                <Save size={15} />
                {saving ? "Saving…" : saved ? "Saved!" : "Save Changes"}
              </button>

              {/* Emergency close all */}
              <section className="border-t border-border-subtle pt-5">
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <AlertTriangle size={12} className="text-loss" /> Emergency
                </h3>
                <button
                  onClick={handleCloseAll}
                  disabled={closing}
                  className="w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm bg-loss/10 text-loss border border-loss/30 hover:bg-loss/20 transition-all"
                >
                  <X size={15} />
                  {closing ? "Closing…" : "Close All Open Positions"}
                </button>
                <p className="mt-1.5 text-xs text-text-muted text-center">
                  Sells everything at current market price immediately
                </p>
              </section>

            </div>
          </div>
        </div>
      )}
    </>
  );
}
