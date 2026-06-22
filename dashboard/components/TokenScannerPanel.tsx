"use client";

import { useState, useCallback, useEffect } from "react";
import { Zap, RefreshCw, TrendingUp, TrendingDown, Database } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type ScanToken = {
  symbol: string;
  rank: number;
  score: number;
  change_1h: number | null;
  change_4h: number | null;
  change_24h: number | null;
  volume_usdt: number | null;
  volume_spike: number | null;
  rsi_1h: number | null;
  price: number | null;
  sma20_distance: number | null;
  data_source: string | null;
  scanned_at?: string | null;
};

function ScoreBar({ score }: { score: number }) {
  const pct   = Math.round(score * 100);
  const color = score >= 0.65 ? "bg-profit" : score >= 0.40 ? "bg-amber-400" : "bg-loss";
  return (
    <div className="w-full h-0.5 rounded-full bg-white/5 overflow-hidden mt-0.5">
      <div className={cn("h-full rounded-full transition-all duration-500", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

function fmt1h(v: number | null) {
  if (v == null) return "—";
  const pos = v >= 0;
  return <span className={pos ? "text-profit" : "text-loss"}>{pos ? "+" : ""}{v.toFixed(1)}%</span>;
}

function fmtSpike(v: number | null) {
  if (v == null) return "—";
  const hot = v >= 2;
  return <span className={hot ? "text-amber-400" : "text-text-muted"}>{v.toFixed(1)}×</span>;
}

export default function TokenScannerPanel({ competitionMode = false }: { competitionMode?: boolean }) {
  const [tokens, setTokens]     = useState<ScanToken[]>([]);
  const [scanned, setScanned]   = useState<number>(0);
  const [loading, setLoading]   = useState(false);
  const [lastScan, setLastScan] = useState<Date | null>(null);
  const [error, setError]       = useState<string | null>(null);
  const [showAll, setShowAll]   = useState(false);

  // Auto-load cached scan results on mount
  useEffect(() => {
    fetch("/api/proxy/scanner/latest")
      .then(r => r.json())
      .then(data => {
        if (data.tokens?.length) {
          setTokens(data.tokens);
          setScanned(data.count);
          if (data.tokens[0]?.scanned_at) setLastScan(new Date(data.tokens[0].scanned_at));
        }
      })
      .catch(() => {});
  }, []);

  const runScan = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res  = await fetch("/api/proxy/scan", { method: "POST" });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setTokens(data.top_tokens ?? []);
      setScanned(data.scanned ?? 0);
      setLastScan(new Date());
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const ago = lastScan ? Math.round((Date.now() - lastScan.getTime()) / 1000) : null;
  const visible = showAll ? tokens : tokens.slice(0, 10);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-1.5">
            <Zap size={12} className="text-accent" />
            Token Scanner
            {scanned > 0 && (
              <span className="text-[9px] text-text-muted font-normal ml-1">
                {scanned} scanned
              </span>
            )}
          </CardTitle>
          <div className="flex items-center gap-2">
            {tokens.length > 10 && (
              <button
                onClick={() => setShowAll(s => !s)}
                className="text-[9px] text-text-muted hover:text-text-primary transition-colors"
              >
                {showAll ? "Top 10" : `All ${tokens.length}`}
              </button>
            )}
            <button
              onClick={runScan}
              disabled={loading}
              className="flex items-center gap-1 text-[10px] text-text-muted hover:text-text-primary transition-colors disabled:opacity-40"
            >
              <RefreshCw size={10} className={loading ? "animate-spin" : ""} />
              {loading ? "Scanning…" : "Scan"}
            </button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="pt-0">
        {tokens.length === 0 ? (
          <div className="py-5 text-center">
            <p className="text-[11px] text-text-muted">
              {loading ? "Scanning 149 competition tokens…" : "Click Scan to rank tokens by momentum."}
            </p>
          </div>
        ) : (
          <>
            {/* Header row */}
            <div className="grid grid-cols-[16px_1fr_36px_36px_36px_36px] gap-x-2 px-1 mb-1 text-[9px] text-text-muted/60 uppercase tracking-wide">
              <span>#</span>
              <span>Token</span>
              <span className="text-right">1h</span>
              <span className="text-right">Spike</span>
              <span className="text-right">RSI</span>
              <span className="text-right">Pts</span>
            </div>

            <div className="space-y-0">
              {visible.map((t) => {
                const rankColor = t.rank === 1 ? "text-profit" : t.rank === 2 ? "text-accent" : t.rank === 3 ? "text-amber-400" : "text-text-muted/60";
                return (
                  <div key={t.symbol} className="grid grid-cols-[16px_1fr_36px_36px_36px_36px] gap-x-2 items-center py-1.5 border-b border-border-subtle/30 last:border-0 px-1">
                    <span className={cn("text-[10px] font-bold tabular-nums", rankColor)}>
                      {t.rank}
                    </span>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1">
                        <span className="text-[12px] font-bold text-text-primary">{t.symbol}</span>
                        {t.data_source === "dexscreener" && (
                          <Database size={7} className="text-text-muted/50 shrink-0" />
                        )}
                      </div>
                      <ScoreBar score={t.score} />
                    </div>
                    <span className="text-[10px] tabular-nums text-right">{fmt1h(t.change_1h)}</span>
                    <span className="text-[10px] tabular-nums text-right">{fmtSpike(t.volume_spike)}</span>
                    <span className="text-[10px] tabular-nums text-right text-text-muted">
                      {t.rsi_1h != null ? t.rsi_1h.toFixed(0) : "—"}
                    </span>
                    <span className="text-[10px] font-mono tabular-nums text-right text-text-muted">
                      {(t.score * 100).toFixed(0)}
                    </span>
                  </div>
                );
              })}
            </div>

            <p className="text-[9px] text-text-muted/50 mt-2">
              Score: 1h(30%) + 4h(20%) + spike(25%) + RSI(15%) + SMA(10%)
              {ago != null && ` · ${ago < 60 ? `${ago}s` : `${Math.round(ago / 60)}m`} ago`}
            </p>
          </>
        )}

        {error && <p className="text-[10px] text-loss mt-2">{error}</p>}
      </CardContent>
    </Card>
  );
}
