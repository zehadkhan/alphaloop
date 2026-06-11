"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, TrendingUp, Clock, SkipForward, AlertCircle, XCircle, Brain } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { timeAgo } from "@/lib/utils";
import type { ActivityItem } from "@/types";

const DOT_COLORS: Record<ActivityItem["color"], string> = {
  green:  "bg-profit",
  yellow: "bg-yellow-400",
  orange: "bg-orange-400",
  red:    "bg-loss",
  gray:   "bg-text-muted/50",
  blue:   "bg-accent animate-pulse",
};

const TITLE_COLORS: Record<ActivityItem["color"], string> = {
  green:  "text-profit",
  yellow: "text-yellow-400",
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
  running:   Clock,
  completed: Brain,
};

function ActivityRow({ item }: { item: ActivityItem }) {
  const [expanded, setExpanded] = useState(false);

  const dotClass   = DOT_COLORS[item.color] ?? "bg-text-muted/50";
  const titleClass = TITLE_COLORS[item.color] ?? "text-text-primary";
  const Icon       = TYPE_ICONS[item.type] ?? Brain;

  return (
    <div className="flex gap-3 py-3.5 border-b border-border-subtle/40 last:border-0">
      {/* Icon + timeline dot */}
      <div className="flex flex-col items-center gap-1 pt-0.5 shrink-0">
        <div className={`w-2 h-2 rounded-full mt-1 ${dotClass}`} />
      </div>

      <div className="flex-1 min-w-0">
        {/* Title row */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Icon size={13} className={`shrink-0 ${TITLE_COLORS[item.color]}`} />
            <p className={`text-sm font-medium leading-snug ${titleClass}`}>
              {item.title}
            </p>
          </div>
          <span className="text-xs text-text-muted shrink-0 pt-0.5 whitespace-nowrap">
            {timeAgo(item.time)}
          </span>
        </div>

        {/* Detail line */}
        {item.detail && (
          <p className="mt-1 ml-5 text-xs text-text-muted leading-relaxed">
            {item.detail}
          </p>
        )}

        {/* Key numbers for a trade */}
        {item.type === "trade" && item.entry_price != null && (
          <div className="mt-2 ml-5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
            {item.confidence != null && (
              <span className="text-profit font-medium">
                {Math.round(item.confidence * 100)}% confident
              </span>
            )}
            {item.stop_loss != null && (
              <span>SL ${item.stop_loss.toLocaleString("en-US", { maximumFractionDigits: 2 })}</span>
            )}
            {item.take_profit != null && (
              <span>TP ${item.take_profit.toLocaleString("en-US", { maximumFractionDigits: 2 })}</span>
            )}
            {item.duration_s != null && (
              <span>took {item.duration_s}s</span>
            )}
          </div>
        )}

        {/* Expand/collapse reasoning */}
        {item.reasoning && (
          <>
            <button
              onClick={() => setExpanded((v) => !v)}
              className="mt-2 ml-5 flex items-center gap-1 text-xs text-accent/70 hover:text-accent transition-colors"
            >
              {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
              {expanded ? "Hide" : "See"} Claude's reasoning
            </button>

            {expanded && (
              <div className="mt-2 ml-5 px-3 py-2.5 bg-surface-2/60 rounded-lg border border-border-subtle/50">
                <p className="text-xs text-text-secondary leading-relaxed">
                  {item.reasoning}
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

type Props = {
  items: ActivityItem[];
};

export default function ActivityFeed({ items }: Props) {
  const display = items.slice(0, 10);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div>
          <CardTitle>What the Bot is Doing</CardTitle>
          <p className="text-xs text-text-muted mt-0.5">
            Every 30 minutes, Claude reads the market and decides: Buy, Wait, or Skip
          </p>
        </div>
        <span className="text-xs text-text-muted bg-surface-2 px-2 py-0.5 rounded-full">
          {items.length} cycles
        </span>
      </CardHeader>
      <CardContent>
        {display.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 gap-2 text-text-muted">
            <Brain size={22} className="opacity-40" />
            <p className="text-sm">No activity yet</p>
            <p className="text-xs opacity-70">Click &quot;Run Now&quot; in the header to trigger the first cycle</p>
          </div>
        ) : (
          <div>
            {display.map((item) => (
              <ActivityRow key={item.id} item={item} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
