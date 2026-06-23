import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "—";
  const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function timeUntil(dateStr: string | null): string {
  if (!dateStr) return "—";
  const diff = Math.floor((new Date(dateStr).getTime() - Date.now()) / 1000);
  if (diff <= 0) return "now";
  if (diff < 60) return `in ${diff}s`;
  if (diff < 3600) return `in ${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `in ${Math.floor(diff / 3600)}h`;
  return `in ${Math.floor(diff / 86400)}d`;
}

export function formatPrice(n: number | null | undefined, decimals?: number): string {
  if (n == null) return "—";
  if (decimals !== undefined) {
    return "$" + n.toLocaleString("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }
  const ap = Math.abs(n);
  let d = 2;
  if (ap < 0.000001) d = 10;
  else if (ap < 0.0001) d = 8;
  else if (ap < 0.01) d = 6;
  else if (ap < 1) d = 4;
  return "$" + n.toLocaleString("en-US", {
    minimumFractionDigits: Math.min(2, d),
    maximumFractionDigits: d,
  });
}

export function bscscanTxUrl(txHash: string): string {
  return `https://bscscan.com/tx/${txHash}`;
}

export function shortenHash(hash: string, head = 8, tail = 6): string {
  if (hash.length <= head + tail + 1) return hash;
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}

export function formatPct(n: number | null | undefined, decimals = 2): string {
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(decimals)}%`;
}

export function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const s = new Date(start);
  const e = end ? new Date(end) : new Date();
  const ms = e.getTime() - s.getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

export function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
