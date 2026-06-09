import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold tracking-wide transition-colors",
  {
    variants: {
      variant: {
        buy: "bg-profit/20 text-profit border border-profit/30",
        sell: "bg-loss/20 text-loss border border-loss/30",
        hold: "bg-amber-500/20 text-amber-400 border border-amber-500/30",
        approved: "bg-profit/20 text-profit border border-profit/30",
        rejected: "bg-loss/20 text-loss border border-loss/30",
        pending: "bg-accent/20 text-accent border border-accent/30",
        executed: "bg-profit/20 text-profit border border-profit/30",
        "dry_run": "bg-slate-700/60 text-slate-400 border border-slate-600/50",
        failed: "bg-loss/20 text-loss border border-loss/30",
        running: "bg-profit/20 text-profit border border-profit/30",
        idle: "bg-slate-700/60 text-slate-400 border border-slate-600/50",
        low: "bg-profit/20 text-profit border border-profit/30",
        medium: "bg-amber-500/20 text-amber-400 border border-amber-500/30",
        high: "bg-loss/20 text-loss border border-loss/30",
        default: "bg-surface-2 text-text-secondary border border-border-subtle",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

type BadgeVariant = VariantProps<typeof badgeVariants>["variant"];

export function Badge({
  variant,
  className,
  children,
}: {
  variant?: BadgeVariant;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span className={cn(badgeVariants({ variant }), className)}>
      {children}
    </span>
  );
}
