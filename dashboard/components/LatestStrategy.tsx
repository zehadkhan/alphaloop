import { Brain, TrendingUp, TrendingDown, Minus, ShieldAlert, Target, ArrowUpDown } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatPrice, formatPct, timeAgo } from "@/lib/utils";
import type { Strategy } from "@/types";

type Props = {
  strategy: Strategy | undefined;
};

function PriceRow({
  label,
  value,
  color,
  icon: Icon,
}: {
  label: string;
  value: number;
  color: string;
  icon: React.ElementType;
}) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-border-subtle last:border-0">
      <div className="flex items-center gap-2 text-text-muted text-sm">
        <Icon size={13} className={color} />
        {label}
      </div>
      <span className={`tabular-nums font-semibold text-sm ${color}`}>
        {formatPrice(value)}
      </span>
    </div>
  );
}

function ConfidenceBar({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const color =
    pct >= 70 ? "#00c076" : pct >= 50 ? "#f59e0b" : "#ff3b69";
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-text-muted">Confidence</span>
        <span className="font-semibold" style={{ color }}>{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

export default function LatestStrategy({ strategy }: Props) {
  if (!strategy) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Latest Strategy</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-12 text-text-muted">
            <Brain size={32} className="mb-3 opacity-30" />
            <p className="text-sm">No strategies generated yet</p>
            <p className="text-xs mt-1">Run the agent to generate a strategy</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const actionVariant =
    strategy.action === "BUY"
      ? "buy"
      : strategy.action === "SELL"
      ? "sell"
      : "hold";

  const ActionIcon =
    strategy.action === "BUY"
      ? TrendingUp
      : strategy.action === "SELL"
      ? TrendingDown
      : Minus;

  const rrRatio =
    strategy.stop_loss && strategy.take_profit && strategy.entry_price
      ? Math.abs(strategy.take_profit - strategy.entry_price) /
        Math.max(Math.abs(strategy.stop_loss - strategy.entry_price), 0.01)
      : null;

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 pb-0">
        <div className="flex items-center gap-3">
          <CardTitle>Latest Strategy</CardTitle>
          <span className="text-xs text-text-muted">#{strategy.id}</span>
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <Badge variant={actionVariant} className="text-sm px-3 py-1">
            <ActionIcon size={12} />
            {strategy.action}
          </Badge>
          <Badge variant={strategy.status as "approved" | "rejected" | "pending"}>
            {strategy.status.toUpperCase()}
          </Badge>
          {strategy.backtest_passed !== null && (
            <Badge variant={strategy.backtest_passed ? "approved" : "rejected"}>
              BT {strategy.backtest_passed ? "PASS" : "FAIL"}
            </Badge>
          )}
          <span className="text-xs text-text-muted">{timeAgo(strategy.created_at)}</span>
        </div>
      </CardHeader>

      <CardContent className="pt-4">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left: Price levels + metadata */}
          <div className="space-y-4">
            <ConfidenceBar confidence={strategy.confidence} />

            <div className="rounded-lg bg-surface-2 border border-border-subtle overflow-hidden">
              <PriceRow
                label="Entry Price"
                value={strategy.entry_price}
                color="text-text-primary"
                icon={ArrowUpDown}
              />
              <PriceRow
                label="Stop Loss"
                value={strategy.stop_loss}
                color="text-loss"
                icon={ShieldAlert}
              />
              <PriceRow
                label="Take Profit"
                value={strategy.take_profit}
                color="text-profit"
                icon={Target}
              />
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-lg bg-surface-2 p-3 text-center">
                <p className="text-xs text-text-muted mb-1">R/R Ratio</p>
                <p className="text-sm font-bold text-text-primary tabular-nums">
                  {rrRatio != null ? `1:${rrRatio.toFixed(1)}` : "—"}
                </p>
              </div>
              <div className="rounded-lg bg-surface-2 p-3 text-center">
                <p className="text-xs text-text-muted mb-1">Timeframe</p>
                <p className="text-sm font-bold text-text-primary capitalize">
                  {strategy.timeframe}
                </p>
              </div>
              <div className="rounded-lg bg-surface-2 p-3 text-center">
                <p className="text-xs text-text-muted mb-1">Risk</p>
                <Badge variant={strategy.risk_level} className="text-[11px]">
                  {strategy.risk_level.toUpperCase()}
                </Badge>
              </div>
            </div>

            {/* Backtest metrics */}
            {strategy.backtest_return !== null && (
              <div className="rounded-lg bg-surface-2 border border-border-subtle p-3">
                <p className="text-xs text-text-muted uppercase tracking-wider mb-2">
                  Backtest Results
                </p>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <p className="text-[10px] text-text-muted">Return</p>
                    <p
                      className={`text-sm font-bold tabular-nums ${
                        (strategy.backtest_return ?? 0) >= 0
                          ? "text-profit"
                          : "text-loss"
                      }`}
                    >
                      {formatPct(strategy.backtest_return)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-text-muted">Win Rate</p>
                    <p className="text-sm font-bold tabular-nums text-text-primary">
                      {strategy.backtest_win_rate != null
                        ? `${(strategy.backtest_win_rate * 100).toFixed(0)}%`
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-text-muted">Symbol</p>
                    <p className="text-sm font-bold text-text-primary">
                      {strategy.symbol}/USDT
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Right: AI Reasoning */}
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <Brain size={14} className="text-accent" />
              <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
                AI Reasoning
              </p>
            </div>
            <div className="flex-1 rounded-lg bg-surface-2 border border-border-subtle p-4">
              <p className="text-sm text-text-secondary leading-relaxed">
                {strategy.reasoning}
              </p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
