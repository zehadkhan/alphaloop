"use client";

import { TrendingUp, TrendingDown, Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { timeAgo } from "@/lib/utils";
import type { Trade, Strategy } from "@/types";

type Props = {
  trades: Trade[];
  strategies: Strategy[];
  currentPrice: number | null;
};

function pctColor(pct: number) {
  if (pct > 0) return "text-profit";
  if (pct < 0) return "text-loss";
  return "text-text-secondary";
}

export default function OpenPositions({ trades, strategies, currentPrice }: Props) {
  const strategyMap = new Map(strategies.map((s) => [s.id, s]));

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

            return (
              <div key={trade.id} className="px-4 py-3 hover:bg-surface-2 transition-colors">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-bold text-text-primary">{trade.symbol}</span>
                      <span className="text-[10px] font-medium text-profit bg-profit/10 px-1.5 py-0.5 rounded">
                        BUY
                      </span>
                      <span className="text-[10px] text-text-muted">#{trade.id}</span>
                    </div>

                    <div className="grid grid-cols-3 gap-x-4 gap-y-0.5 text-[11px]">
                      <div>
                        <span className="text-text-muted">Entry</span>
                        <span className="ml-1 tabular-nums text-text-secondary">
                          ${entry.toFixed(2)}
                        </span>
                      </div>
                      {tp && (
                        <div>
                          <TrendingUp size={9} className="inline text-profit mr-0.5" />
                          <span className="text-text-muted">TP</span>
                          <span className="ml-1 tabular-nums text-profit">
                            ${tp.toFixed(2)}
                            {tpDistPct != null && (
                              <span className="text-[10px] opacity-70"> +{tpDistPct.toFixed(1)}%</span>
                            )}
                          </span>
                        </div>
                      )}
                      {sl && (
                        <div>
                          <TrendingDown size={9} className="inline text-loss mr-0.5" />
                          <span className="text-text-muted">SL</span>
                          <span className="ml-1 tabular-nums text-loss">
                            ${sl.toFixed(2)}
                            {slDistPct != null && (
                              <span className="text-[10px] opacity-70"> {slDistPct.toFixed(1)}%</span>
                            )}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="text-right shrink-0">
                    {unrealizedPct != null && (
                      <p className={`text-sm font-bold tabular-nums ${pctColor(unrealizedPct)}`}>
                        {unrealizedPct > 0 ? "+" : ""}{unrealizedPct.toFixed(2)}%
                      </p>
                    )}
                    <div className="flex items-center gap-1 justify-end mt-0.5">
                      <Clock size={9} className="text-text-muted" />
                      <span className="text-[10px] text-text-muted">
                        {trade.executed_at ? timeAgo(trade.executed_at) : "—"}
                      </span>
                    </div>
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
