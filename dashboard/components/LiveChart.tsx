"use client";

import { useEffect, useState, useRef } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Trade, Strategy } from "@/types";

type Candle = { time: string; price: number };

type Props = {
  trades: Trade[];
  strategies: Strategy[];
};

function fmtTime(ms: number) {
  return new Date(ms).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function fmtLabel(n: number) {
  return `$${n.toFixed(2)}`;
}

export default function LiveChart({ trades, strategies }: Props) {
  const [candles, setCandles] = useState<Candle[]>([]);
  const [currentPrice, setCurrentPrice] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const prevPrice = useRef<number | null>(null);
  const [priceUp, setPriceUp] = useState<boolean | null>(null);

  // most-recent open BUY position (trades come in newest-first)
  const openTrade =
    trades.find(
      (t) =>
        t.action === "BUY" &&
        t.closed_at === null &&
        (t.status === "dry_run" || t.status === "executed")
    ) ?? null;
  const openStrategy = openTrade?.strategy_id
    ? (strategies.find((s) => s.id === openTrade.strategy_id) ?? null)
    : null;

  // dynamic symbol — track open position or fallback to BNB
  const symbol = openTrade?.symbol ?? "BNB";
  const binancePair = symbol.toUpperCase() + "USDT";

  // fetch 48 × 1h candles on mount and when symbol changes
  useEffect(() => {
    setLoading(true);
    setCandles([]);
    fetch(
      `https://api.binance.com/api/v3/klines?symbol=${binancePair}&interval=1h&limit=48`
    )
      .then((r) => r.json())
      .then((rows: number[][]) => {
        setCandles(
          rows.map((k) => ({ time: fmtTime(k[0]), price: parseFloat(String(k[4])) }))
        );
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [binancePair]);

  // poll live price every 5 s
  useEffect(() => {
    prevPrice.current = null;
    const update = () => {
      fetch(`https://api.binance.com/api/v3/ticker/price?symbol=${binancePair}`)
        .then((r) => r.json())
        .then((d) => {
          const p = parseFloat(d.price);
          if (prevPrice.current !== null) setPriceUp(p >= prevPrice.current);
          prevPrice.current = p;
          setCurrentPrice(p);
        })
        .catch(() => {});
    };
    update();
    const id = setInterval(update, 5000);
    return () => clearInterval(id);
  }, [binancePair]);

  // replace the last candle with the live price so the chart edge is always current
  const chartData =
    candles.length > 0 && currentPrice != null
      ? [...candles.slice(0, -1), { time: "Now", price: currentPrice }]
      : candles;

  // compute Y-axis domain wide enough to include TP and SL
  const prices = chartData.map((c) => c.price);
  if (openTrade) prices.push(openTrade.entry_price);
  if (openStrategy) prices.push(openStrategy.take_profit, openStrategy.stop_loss);
  const minP = prices.length ? Math.min(...prices) : 0;
  const maxP = prices.length ? Math.max(...prices) : 1;
  const pad = (maxP - minP) * 0.06 || 5;
  const domain: [number, number] = [minP - pad, maxP + pad];

  const unrealizedPct =
    openTrade && currentPrice != null
      ? ((currentPrice - openTrade.entry_price) / openTrade.entry_price) * 100
      : null;
  const unrealizedUsd =
    openTrade && currentPrice != null
      ? (currentPrice / openTrade.entry_price - 1) * openTrade.amount_usd
      : null;

  const pColor =
    priceUp === null
      ? "text-text-primary"
      : priceUp
      ? "text-profit"
      : "text-loss";

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="text-sm font-semibold text-text-primary">
              {symbol}/USDT — Live Chart
            </CardTitle>
            <p className="text-[10px] text-text-muted mt-0.5">
              48h · 1h candles · refreshes every 5s
            </p>
          </div>

          {/* Live price */}
          <div className="text-right shrink-0">
            {currentPrice != null ? (
              <>
                <p
                  className={cn(
                    "text-2xl font-bold tabular-nums transition-colors duration-300",
                    pColor
                  )}
                >
                  {fmtLabel(currentPrice)}
                </p>
                <div className="flex items-center justify-end gap-1.5 mt-1">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-profit opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-profit" />
                  </span>
                  <span className="text-[10px] text-text-muted">live</span>
                </div>
              </>
            ) : (
              <div className="h-8 w-24 bg-surface-2 rounded animate-pulse" />
            )}
          </div>
        </div>

        {/* Open trade summary strip */}
        {openTrade && (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 mt-3 pt-3 border-t border-border-subtle text-xs">
            <div>
              <span className="text-text-muted">Entry </span>
              <span className="tabular-nums text-text-secondary font-medium">
                {fmtLabel(openTrade.entry_price)}
              </span>
            </div>
            {openStrategy && (
              <>
                <div>
                  <span className="text-text-muted">TP </span>
                  <span className="tabular-nums text-profit font-medium">
                    {fmtLabel(openStrategy.take_profit)}
                  </span>
                  <span className="text-text-muted ml-1 text-[10px]">
                    (+
                    {(
                      ((openStrategy.take_profit - openTrade.entry_price) /
                        openTrade.entry_price) *
                      100
                    ).toFixed(1)}
                    %)
                  </span>
                </div>
                <div>
                  <span className="text-text-muted">SL </span>
                  <span className="tabular-nums text-loss font-medium">
                    {fmtLabel(openStrategy.stop_loss)}
                  </span>
                  <span className="text-text-muted ml-1 text-[10px]">
                    (
                    {(
                      ((openStrategy.stop_loss - openTrade.entry_price) /
                        openTrade.entry_price) *
                      100
                    ).toFixed(1)}
                    %)
                  </span>
                </div>
              </>
            )}
            {unrealizedPct !== null && (
              <div className="ml-auto">
                <span className="text-text-muted">Unrealized </span>
                <span
                  className={cn(
                    "tabular-nums font-semibold",
                    unrealizedPct >= 0 ? "text-profit" : "text-loss"
                  )}
                >
                  {unrealizedPct >= 0 ? "+" : ""}
                  {unrealizedPct.toFixed(2)}%
                </span>
                {unrealizedUsd !== null && (
                  <span className="text-text-muted ml-1">
                    ({unrealizedUsd >= 0 ? "+" : ""}${unrealizedUsd.toFixed(2)})
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </CardHeader>

      <CardContent className="pt-0">
        {loading ? (
          <div className="h-[240px] rounded-lg bg-surface-2 animate-pulse" />
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart
              data={chartData}
              margin={{ top: 4, right: 56, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00c076" stopOpacity={0.18} />
                  <stop offset="95%" stopColor="#00c076" stopOpacity={0} />
                </linearGradient>
              </defs>

              <CartesianGrid
                strokeDasharray="3 3"
                stroke="var(--border-subtle)"
                vertical={false}
              />
              <XAxis
                dataKey="time"
                tick={{ fontSize: 9, fill: "var(--text-muted)" }}
                tickLine={false}
                axisLine={false}
                interval={7}
              />
              <YAxis
                domain={domain}
                tick={{ fontSize: 9, fill: "var(--text-muted)" }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                width={44}
              />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null;
                  const val = payload[0].value as number;
                  return (
                    <div className="bg-surface border border-border-subtle rounded-lg px-3 py-2 text-xs shadow-lg">
                      <p className="text-text-muted mb-0.5">{label}</p>
                      <p className="font-bold tabular-nums text-text-primary">
                        {fmtLabel(val)}
                      </p>
                    </div>
                  );
                }}
              />

              <Area
                type="monotone"
                dataKey="price"
                stroke="#00c076"
                strokeWidth={1.5}
                fill="url(#priceGrad)"
                dot={false}
                activeDot={{ r: 3, strokeWidth: 0, fill: "#00c076" }}
                isAnimationActive={false}
              />

              {/* Entry level — amber */}
              {openTrade && (
                <ReferenceLine
                  y={openTrade.entry_price}
                  stroke="#f59e0b"
                  strokeDasharray="6 4"
                  strokeWidth={1.5}
                  label={{
                    value: `Entry ${fmtLabel(openTrade.entry_price)}`,
                    position: "right",
                    fontSize: 9,
                    fill: "#f59e0b",
                  }}
                />
              )}

              {/* Take-profit — green */}
              {openStrategy && (
                <ReferenceLine
                  y={openStrategy.take_profit}
                  stroke="#00c076"
                  strokeDasharray="6 4"
                  strokeWidth={1.5}
                  label={{
                    value: `TP ${fmtLabel(openStrategy.take_profit)}`,
                    position: "right",
                    fontSize: 9,
                    fill: "#00c076",
                  }}
                />
              )}

              {/* Stop-loss — red */}
              {openStrategy && (
                <ReferenceLine
                  y={openStrategy.stop_loss}
                  stroke="#ff3b69"
                  strokeDasharray="6 4"
                  strokeWidth={1.5}
                  label={{
                    value: `SL ${fmtLabel(openStrategy.stop_loss)}`,
                    position: "right",
                    fontSize: 9,
                    fill: "#ff3b69",
                  }}
                />
              )}
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
