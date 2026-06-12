"use client";

import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  TrendingUp,
  Clock,
  SkipForward,
  AlertCircle,
  XCircle,
  Brain,
  Zap,
  CheckCircle,
} from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { timeAgo } from "@/lib/utils";
import type { ActivityItem } from "@/types";

// ─── Color / icon maps ────────────────────────────────────────────────────────
const DOT_COLORS: Record<ActivityItem["color"], string> = {
  green:  "bg-profit",
  yellow: "bg-amber-400",
  orange: "bg-orange-400",
  red:    "bg-loss",
  gray:   "bg-text-muted/40",
  blue:   "bg-accent animate-pulse",
};

const TITLE_COLORS: Record<ActivityItem["color"], string> = {
  green:  "text-profit",
  yellow: "text-amber-400",
  orange: "text-orange-400",
  red:    "text-loss",
  gray:   "text-text-primary",
  blue:   "text-accent",
};

const TYPE_ICONS: Record<ActivityItem["type"], React.ElementType> = {
  trade:     TrendingUp,
  hold:      Clock,
  rejected:  XCircle,
  skipped:   SkipForward,
  error:     AlertCircle,
  running:   Zap,
  completed: CheckCircle,
};

// ─── ActivityRow ──────────────────────────────────────────────────────────────
function ActivityRow({
  item,
  isLast,
}: {
  item: ActivityItem;
  isLast: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  const dotClass   = DOT_COLORS[item.color]   ?? "bg-text-muted/40";
  const titleClass = TITLE_COLORS[item.color] ?? "text-text-primary";
  const Icon       = TYPE_ICONS[item.type]    ?? Brain;

  return (
    <div className="relative pl-8">
      {/* Vertical timeline connector */}
      {!isLast && (
        <div className="absolute left-[5px] top-5 bottom-0 w-px bg-border-subtle/50" />
      )}

      {/* Timeline dot */}
      <div
        className={[
          "absolute left-0 top-2 w-3 h-3 rounded-full border-2 border-background",
          dotClass,
        ].join(" ")}
      />

      {/* Content */}
      <div className="pb-5">
        {/* Title row */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <Icon size={13} className={`shrink-0 ${titleClass}`} />
            <p className={`text-sm font-medium leading-snug ${titleClass}`}>
              {item.title}
            </p>
          </div>
          <span className="text-xs text-text-muted shrink-0 whitespace-nowrap pt-0.5">
            {timeAgo(item.time)}
          </span>
        </div>

        {/* Detail line */}
        {item.detail && (
          <p className="mt-1 text-xs text-text-muted leading-relaxed">
            {item.detail}
          </p>
        )}

        {/* Trade pills: confidence, SL, TP */}
        {item.type === "trade" && item.entry_price != null && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {item.confidence != null && (
              <span className="text-[10px] bg-profit/10 text-profit border border-profit/20 px-2 py-0.5 rounded-full font-mono font-semibold">
                {Math.round(item.confidence * 100)}% conf
              </span>
            )}
            {item.stop_loss != null && (
              <span className="text-[10px] bg-white/5 text-text-muted border border-border-subtle px-2 py-0.5 rounded-full font-mono">
                SL&nbsp;$
                {item.stop_loss.toLocaleString("en-US", {
                  maximumFractionDigits: 2,
                })}
              </span>
            )}
            {item.take_profit != null && (
              <span className="text-[10px] bg-white/5 text-text-muted border border-border-subtle px-2 py-0.5 rounded-full font-mono">
                TP&nbsp;$
                {item.take_profit.toLocaleString("en-US", {
                  maximumFractionDigits: 2,
                })}
              </span>
            )}
            {item.duration_s != null && (
              <span className="text-[10px] bg-white/5 text-text-muted border border-border-subtle px-2 py-0.5 rounded-full font-mono">
                {item.duration_s}s
              </span>
            )}
          </div>
        )}

        {/* Expand / collapse Claude reasoning */}
        {item.reasoning && (
          <div className="mt-2">
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex items-center gap-1 text-xs text-accent/70 hover:text-accent transition-colors"
            >
              {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
              {expanded ? "Hide reasoning" : "See reasoning"}
            </button>

            {expanded && (
              <div className="mt-2 bg-surface-2 rounded-xl px-4 py-3 border border-border-subtle">
                <p className="text-xs text-text-secondary leading-relaxed whitespace-pre-line">
                  {item.reasoning}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── ActivityFeed ─────────────────────────────────────────────────────────────
type Props = {
  items: ActivityItem[];
};

export default function ActivityFeed({ items }: Props) {
  const display = items.slice(0, 12);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3 gap-3">
        <div className="min-w-0">
          <CardTitle>What the Bot is Doing</CardTitle>
          <p className="text-xs text-text-muted mt-0.5">
            Every 30 min, Claude reads the market and decides
          </p>
        </div>

        {/* Items count badge */}
        {items.length > 0 && (
          <span className="shrink-0 text-[10px] font-semibold text-text-muted bg-white/5 border border-border-subtle px-2.5 py-1 rounded-full tabular-nums">
            {items.length} cycles
          </span>
        )}
      </CardHeader>

      <CardContent>
        {display.length === 0 ? (
          /* Empty state */
          <div className="flex flex-col items-center justify-center py-12 gap-3 text-text-muted">
            <div className="w-12 h-12 rounded-2xl bg-white/5 border border-border-subtle flex items-center justify-center">
              <Brain size={22} className="opacity-40" />
            </div>
            <p className="text-sm font-medium">No activity yet</p>
            <p className="text-xs opacity-60 text-center max-w-[220px] leading-relaxed">
              Click &quot;Run Now&quot; in the header to trigger the first cycle
            </p>
          </div>
        ) : (
          <div>
            {display.map((item, i) => (
              <ActivityRow
                key={item.id}
                item={item}
                isLast={i === display.length - 1}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
