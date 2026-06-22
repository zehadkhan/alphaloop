import { ArrowUpRight, ArrowDownRight, Minus } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatPrice, formatPct, timeAgo } from "@/lib/utils";
import type { Trade } from "@/types";

type Props = {
  trades: Trade[];
};

function ActionIcon({ action }: { action: string }) {
  if (action === "BUY") return <ArrowUpRight size={12} className="text-profit" />;
  if (action === "SELL") return <ArrowDownRight size={12} className="text-loss" />;
  return <Minus size={12} className="text-text-muted" />;
}

function PnlCell({ pnl }: { pnl: number | null }) {
  if (pnl == null) return <span className="text-text-muted">—</span>;
  const color = pnl > 0 ? "text-profit" : pnl < 0 ? "text-loss" : "text-text-muted";
  return (
    <span className={`font-semibold tabular-nums ${color}`}>
      {formatPct(pnl)}
    </span>
  );
}

export default function TradeHistory({ trades }: Props) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Trade History</CardTitle>
        <span className="text-xs text-text-muted">{trades.length} total</span>
      </CardHeader>
      <CardContent className="p-0">
        {trades.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-text-muted">
            <p className="text-sm">No trades recorded yet</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-subtle">
                  {["#", "Symbol", "Action", "Entry", "Exit", "PnL %", "Dur.", "Reason", "Status", "Time"].map(
                    (h) => (
                      <th
                        key={h}
                        className="px-4 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider whitespace-nowrap"
                      >
                        {h}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody>
                {trades.map((trade, i) => {
                  const isDryRun = trade.status === "dry_run";
                  const isProfit = (trade.pnl_percent ?? 0) > 0;
                  const isLoss = (trade.pnl_percent ?? 0) < 0;
                  const rowBg = isDryRun
                    ? ""
                    : isProfit
                    ? "bg-profit/[0.03]"
                    : isLoss
                    ? "bg-loss/[0.03]"
                    : "";

                  return (
                    <tr
                      key={trade.id}
                      className={`border-b border-border-subtle/50 hover:bg-surface-2 transition-colors ${rowBg}`}
                    >
                      <td className="px-4 py-3 text-text-muted tabular-nums">{i + 1}</td>
                      <td className="px-4 py-3 font-semibold text-text-primary whitespace-nowrap">
                        {trade.symbol}/USDT
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <ActionIcon action={trade.action} />
                          <Badge
                            variant={trade.action.toLowerCase() as "buy" | "sell"}
                            className="text-[11px]"
                          >
                            {trade.action}
                          </Badge>
                        </div>
                      </td>
                      <td className="px-4 py-3 tabular-nums text-text-primary whitespace-nowrap">
                        {formatPrice(trade.entry_price)}
                      </td>
                      <td className="px-4 py-3 tabular-nums text-text-secondary whitespace-nowrap">
                        {trade.exit_price ? formatPrice(trade.exit_price) : "—"}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <PnlCell pnl={trade.pnl_percent} />
                      </td>
                      <td className="px-4 py-3 tabular-nums text-text-muted whitespace-nowrap text-[11px]">
                        {(trade as any).duration_hours != null
                          ? `${((trade as any).duration_hours as number).toFixed(1)}h`
                          : "—"}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {(trade as any).close_reason ? (
                          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                            (trade as any).close_reason === "TP" ? "bg-profit/10 text-profit" :
                            (trade as any).close_reason === "SL" ? "bg-loss/10 text-loss" :
                            (trade as any).close_reason === "timeout" ? "bg-amber-400/10 text-amber-400" :
                            "bg-white/5 text-text-muted"
                          }`}>
                            {(trade as any).close_reason}
                          </span>
                        ) : (
                          <span className="text-text-muted text-[11px]">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant={
                            trade.status === "executed"
                              ? "executed"
                              : trade.status === "dry_run"
                              ? "dry_run"
                              : trade.status === "failed"
                              ? "failed"
                              : "pending"
                          }
                          className="text-[11px]"
                        >
                          {isDryRun ? "DRY RUN" : trade.status.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-text-muted whitespace-nowrap">
                        {timeAgo(trade.executed_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
