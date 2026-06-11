"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Trade } from "@/types";

type Props = {
  trades: Trade[];
};

type DataPoint = {
  date: string;
  cumPnl: number;
  pnl: number;
};

function buildEquitySeries(trades: Trade[]): DataPoint[] {
  const closed = trades
    .filter((t) => t.pnl_usd != null && t.closed_at != null)
    .sort((a, b) => new Date(a.closed_at!).getTime() - new Date(b.closed_at!).getTime());

  let cumPnl = 0;
  return closed.map((t) => {
    const pnl = t.pnl_usd!;
    cumPnl += pnl;
    return {
      date: new Date(t.closed_at!).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      cumPnl: parseFloat(cumPnl.toFixed(2)),
      pnl: parseFloat(pnl.toFixed(2)),
    };
  });
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number; payload: DataPoint }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const color = d.cumPnl >= 0 ? "text-profit" : "text-loss";
  return (
    <div className="bg-surface border border-border-subtle rounded-lg px-3 py-2 text-xs shadow-lg">
      <p className="font-medium text-text-primary mb-1">{label}</p>
      <p className={`font-bold tabular-nums ${color}`}>
        Cumulative: {d.cumPnl >= 0 ? "+" : ""}${d.cumPnl.toFixed(2)}
      </p>
      <p className={`tabular-nums ${d.pnl >= 0 ? "text-profit" : "text-loss"}`}>
        Trade PnL: {d.pnl >= 0 ? "+" : ""}${d.pnl.toFixed(2)}
      </p>
    </div>
  );
}

export default function EquityCurve({ trades }: Props) {
  const data = buildEquitySeries(trades);
  const final = data.at(-1)?.cumPnl ?? 0;
  const isPositive = final >= 0;

  if (data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold text-text-primary">Equity Curve</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-text-muted py-8 text-center">
            No closed trades yet — equity curve will appear here
          </p>
        </CardContent>
      </Card>
    );
  }

  const strokeColor = isPositive ? "var(--profit-hex, #00c076)" : "var(--loss-hex, #ff3b69)";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold text-text-primary">Equity Curve</CardTitle>
          <span className={`text-sm font-bold tabular-nums ${isPositive ? "text-profit" : "text-loss"}`}>
            {isPositive ? "+" : ""}${final.toFixed(2)}
          </span>
        </div>
        <p className="text-xs text-text-muted">{data.length} closed trade{data.length !== 1 ? "s" : ""}</p>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={160}>
          <AreaChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={strokeColor} stopOpacity={0.25} />
                <stop offset="95%" stopColor={strokeColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "var(--text-muted)" }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--text-muted)" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `$${v}`}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="cumPnl"
              stroke={strokeColor}
              strokeWidth={2}
              fill="url(#equityGrad)"
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
