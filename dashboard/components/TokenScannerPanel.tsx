"use client";

import { useState, useCallback } from "react";
import { Zap, RefreshCw, TrendingUp, TrendingDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { TokenScanToken } from "@/types";

function ScoreBar({ score }: { score: number }) {
  const pct   = Math.round(score * 100);
  const color = score >= 0.65 ? "bg-profit" : score >= 0.4 ? "bg-amber-400" : "bg-loss";
  return (
    <div className="w-full h-0.5 rounded-full bg-white/5 overflow-hidden mt-1">
      <div
        className={cn("h-full rounded-full transition-all duration-500", color)}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function TokenRow({ token, rank }: { token: TokenScanToken; rank: number }) {
  const changePos  = token.change_24h >= 0;
  const rankColors = ["text-profit", "text-accent", "text-text-muted"];

  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-border-subtle/50 last:border-0">
      {/* Rank */}
      <span className={cn("text-[11px] font-bold tabular-nums w-3 shrink-0", rankColors[rank] ?? "text-text-muted")}>
        #{rank + 1}
      </span>

      {/* Symbol + score bar */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-[13px] font-bold text-text-primary">{token.symbol}</span>
          <span className="text-[10px] font-mono text-text-muted tabular-nums">
            {(token.score * 100).toFixed(0)}
            <span className="text-text-muted/60">pts</span>
          </span>
        </div>
        <ScoreBar score={token.score} />
      </div>

      {/* Stats */}
      <div className="flex flex-col items-end gap-0.5 shrink-0">
        <span className={cn("text-[11px] font-semibold tabular-nums flex items-center gap-0.5",
          changePos ? "text-profit" : "text-loss")}>
          {changePos ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
          {changePos ? "+" : ""}{token.change_24h.toFixed(1)}%
        </span>
        <span className="text-[9px] text-text-muted tabular-nums">
          RSI {token.rsi.toFixed(0)}
        </span>
      </div>
    </div>
  );
}

type Props = {
  competitionMode?: boolean;
};

export default function TokenScannerPanel({ competitionMode = false }: Props) {
  const [tokens, setTokens]     = useState<TokenScanToken[]>([]);
  const [scanned, setScanned]   = useState<number>(0);
  const [loading, setLoading]   = useState(false);
  const [lastScan, setLastScan] = useState<Date | null>(null);
  const [error, setError]       = useState<string | null>(null);

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

  const ago = lastScan
    ? Math.round((Date.now() - lastScan.getTime()) / 1000)
    : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-1.5">
            <Zap size={12} className="text-accent" />
            Token Scanner
          </CardTitle>
          <button
            onClick={runScan}
            disabled={loading}
            className="flex items-center gap-1 text-[10px] text-text-muted hover:text-text-primary transition-colors disabled:opacity-40"
          >
            <RefreshCw size={10} className={loading ? "animate-spin" : ""} />
            {loading ? "Scanning…" : "Scan Now"}
          </button>
        </div>
      </CardHeader>

      <CardContent className="pt-0">
        {tokens.length === 0 ? (
          <div className="py-5 text-center">
            <p className="text-[11px] text-text-muted leading-relaxed">
              {loading
                ? "Fetching momentum scores from Binance…"
                : "Click Scan Now to rank eligible tokens by momentum."}
            </p>
            {!loading && (
              <p className="text-[10px] text-text-muted/60 mt-1">
                {scanned > 0 ? `${scanned} tokens eligible` : `${competitionMode ? "Competition mode active" : "30 tokens eligible"}`}
              </p>
            )}
          </div>
        ) : (
          <>
            <div className="mb-1">
              {tokens.map((t, i) => (
                <TokenRow key={t.symbol} token={t} rank={i} />
              ))}
            </div>
            <p className="text-[9px] text-text-muted/60 mt-1">
              Top {tokens.length} of {scanned} eligible · scored by RSI + momentum + volume
              {ago != null && ` · ${ago < 60 ? `${ago}s` : `${Math.round(ago / 60)}m`} ago`}
            </p>
          </>
        )}

        {error && (
          <p className="text-[10px] text-loss mt-2 leading-snug">{error}</p>
        )}
      </CardContent>
    </Card>
  );
}
