"use client";

import { useState, useCallback } from "react";
import { TrendingUp, TrendingDown, Clock, X, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { timeAgo } from "@/lib/utils";
import type { Trade, Strategy } from "@/types";

type Props = {
  trades: Trade[];
  strategies: Strategy[];
  currentPrice: number | null;
  onRefresh?: () => void;
};

function pctColor(pct: number) {
  if (pct > 0) return "text-profit";
  if (pct < 0) return "text-loss";
  return "text-text-secondary";
}

export default function OpenPositions({ trades, strategies, currentPrice, onRefresh }: Props) {
  const [closingId, setClosingId] = useState<number | null>(null);
  const strategyMap = new Map(strategies.map((s) => [s.id, s]));

  const handleClose = useCallback(async (tradeId: number) => {
    if (!confirm(`Close trade #${tradeId} at market price?`)) return;
    setClosingId(tradeId);
    try {
      const res = await fetch(`/api/proxy/admin/close/${tradeId}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Close failed");
      onRefresh?.();
    } catch (err) {
      alert(String(err));
    } finally {
      setClosingId(null);
    }
  }, [onRefresh]);

  const open = trades.filter(
    (t) => t.action === "BUY" && t.closed_at === null && (t.status === "dry_run" || t.status === "executed")
  );

  if (open.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold text-text-primary">Open Positions</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-text-muted py-4 text-center">No open positions</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold text-text-primary">Open Positions</CardTitle>
          <span className="text-xs font-medium text-profit bg-profit/10 border border-profit/20 px-2 py-0.5 rounded-full">
            {open.length} live
          </span>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y divide-border-subtle">
          {open.map((trade) => {
            const strategy = trade.strategy_id ? strategyMap.get(trade.strategy_id) : null;
            const tp = strategy?.take_profit ?? null;
            const sl = strategy?.stop_loss ?? null;
            const entry = trade.entry_price;

            const unrealizedPct =
              currentPrice != null ? ((currentPrice - entry) / entry) * 100 : null;

            const tpDistPct = tp ? ((tp - entry) / entry) * 100 : null;
            const slDistPct = sl ? ((sl - entry) / entry) * 100 : null;

            // Time until 4h auto-close
            const autoCloseIn = trade.executed_at
              ? Math.max(0, 4 * 3600 - (Date.now() - new Date(trade.executed_at).getTime()) / 1000)
              : null;
            const autoCloseHrs = autoCloseIn != null ? Math.floor(autoCloseIn / 3600) : null;
            const autoCloseMins = autoCloseIn != null ? Math.floor((autoCloseIn % 3600) / 60) : null;
            const nearTimeout = autoCloseIn != null && autoCloseIn < 1800; // < 30 min

            return (
              <div key={trade.id} className="px-4 py-3 hover:bg-surface-2 transition-colors">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-bold text-text-primary">{trade.symbol}</span>
                      <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                        trade.action === "BUY"
                          ? "text-profit bg-profit/10"
                          : "text-loss bg-loss/10"
                      }`}>
                        {trade.action}
                      </span>
                      <span className="text-[10px] text-text-muted">#{trade.id}</span>
                    </div>

                    <div className="grid grid-cols-3 gap-x-4 gap-y-0.5 text-[11px]">
                      <div>
                        <span className="text-text-muted">Entry</span>
                        <span className="ml-1 tabular-nums text-text-secondary">
                          ${entry.toFixed(4)}
                        </span>
                      </div>
                      {tp && (
                        <div>
                          <TrendingUp size={9} className="inline text-profit mr-0.5" />
                          <span className="text-text-muted">TP</span>
                          <span className="ml-1 tabular-nums text-profit">
                            {tpDistPct != null ? `+${tpDistPct.toFixed(1)}%` : `$${tp.toFixed(4)}`}
                          </span>
                        </div>
                      )}
                      {sl && (
                        <div>
                          <TrendingDown size={9} className="inline text-loss mr-0.5" />
                          <span className="text-text-muted">SL</span>
                          <span className="ml-1 tabular-nums text-loss">
                            {slDistPct != null ? `${slDistPct.toFixed(1)}%` : `$${sl.toFixed(4)}`}
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Auto-close countdown */}
                    {autoCloseIn != null && (
                      <div className={`flex items-center gap-1 mt-1 text-[10px] ${nearTimeout ? "text-amber-400" : "text-text-muted/60"}`}>
                        {nearTimeout && <AlertTriangle size={8} />}
                        <span>
                          Auto-close in {autoCloseHrs}h {autoCloseMins}m
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="flex flex-col items-end gap-1 shrink-0">
                    {unrealizedPct != null && (
                      <p className={`text-sm font-bold tabular-nums ${pctColor(unrealizedPct)}`}>
                        {unrealizedPct > 0 ? "+" : ""}{unrealizedPct.toFixed(2)}%
                      </p>
                    )}
                    <div className="flex items-center gap-1 justify-end">
                      <Clock size={9} className="text-text-muted" />
                      <span className="text-[10px] text-text-muted">
                        {trade.executed_at ? timeAgo(trade.executed_at) : "—"}
                      </span>
                    </div>
                    <button
                      onClick={() => handleClose(trade.id)}
                      disabled={closingId === trade.id}
                      className="flex items-center gap-0.5 text-[9px] text-loss/70 hover:text-loss border border-loss/20 hover:border-loss/50 px-1.5 py-0.5 rounded transition-colors disabled:opacity-40"
                    >
                      <X size={8} />
                      {closingId === trade.id ? "Closing…" : "Close"}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
