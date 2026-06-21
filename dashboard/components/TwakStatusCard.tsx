"use client";

import { Shield, CheckCircle2, XCircle, AlertTriangle, ExternalLink, Zap, FileCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { TwakStatus } from "@/types";

type Props = {
  status: TwakStatus | null;
};

function Row({ label, value, valueClass }: { label: string; value: React.ReactNode; valueClass?: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border-subtle/40 last:border-0">
      <span className="text-[10px] text-text-muted font-medium uppercase tracking-wider">{label}</span>
      <span className={cn("text-[11px] font-semibold font-mono", valueClass ?? "text-text-primary")}>
        {value}
      </span>
    </div>
  );
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={cn("w-1.5 h-1.5 rounded-full", ok ? "bg-profit animate-pulse" : "bg-loss")} />
      <span className={cn("text-[11px] font-semibold", ok ? "text-profit" : "text-loss")}>{label}</span>
    </div>
  );
}

export default function TwakStatusCard({ status }: Props) {
  if (!status) return null;

  const registered  = status.registration?.registered === true || status.registration?.ok === true;
  const walletShort = status.wallet_address
    ? `${status.wallet_address.slice(0, 6)}…${status.wallet_address.slice(-4)}`
    : null;

  return (
    <Card className={cn(!status.twak_configured && "border-amber-400/20")}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-1.5">
            <Shield size={12} className="text-accent" />
            TWAK Signing
          </CardTitle>
          <StatusDot
            ok={status.twak_configured}
            label={status.twak_configured ? "Online" : "Offline"}
          />
        </div>
      </CardHeader>

      <CardContent className="pt-0 space-y-3">
        {!status.twak_configured ? (
          <div className="flex items-start gap-2 px-3 py-2.5 rounded-xl bg-amber-400/5 border border-amber-400/20">
            <AlertTriangle size={12} className="text-amber-400 mt-0.5 shrink-0" />
            <div>
              <p className="text-[11px] font-semibold text-amber-400">TWAK not configured</p>
              <p className="text-[10px] text-text-muted mt-0.5 leading-relaxed">
                Set TWAK_REST_URL in .env and run&nbsp;
                <code className="font-mono bg-white/5 px-1 rounded">twak serve</code>
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-0">
            <Row
              label="Wallet"
              value={walletShort
                ? <span className="flex items-center gap-1">
                    {walletShort}
                    <a
                      href={`https://bscscan.com/address/${status.wallet_address}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent hover:opacity-80"
                    >
                      <ExternalLink size={9} />
                    </a>
                  </span>
                : "—"
              }
            />
            <Row
              label="Registration"
              value={
                <span className={cn("flex items-center gap-1", registered ? "text-profit" : "text-amber-400")}>
                  {registered
                    ? <><CheckCircle2 size={10} /> Registered</>
                    : <><XCircle size={10} /> Not yet</>
                  }
                </span>
              }
            />
          </div>
        )}

        {/* Guardrails */}
        {status.guardrails && (
          <div className="pt-1 space-y-0">
            <p className="text-[9px] text-text-muted/60 uppercase tracking-widest mb-1.5 font-semibold">Guardrails</p>
            <Row label="Max trade"    value={`$${status.guardrails.max_position_usd}`} />
            <Row label="Max drawdown" value={`${status.guardrails.max_drawdown_pct}%`} valueClass="text-amber-400" />
            <Row label="Daily loss"   value={`$${status.guardrails.max_daily_loss_usd}`} />
            <Row
              label="Eligible tokens"
              value={`${status.guardrails.eligible_tokens?.length ?? 0} tokens`}
              valueClass="text-accent"
            />
          </div>
        )}

        {/* Wallet balance */}
        {status.twak_configured && status.balance?.BNB?.price_usdt && (
          <Row
            label="BNB Price"
            value={`$${status.balance.BNB.price_usdt.toLocaleString("en-US", { maximumFractionDigits: 2 })}`}
            valueClass="text-text-primary"
          />
        )}

        {/* x402 + Policy commitment */}
        {status.twak_configured && (
          <div className="pt-1 space-y-0 border-t border-border-subtle/40 mt-1">
            <p className="text-[9px] text-text-muted/60 uppercase tracking-widest mb-1.5 font-semibold">Verifiability</p>
            <Row
              label="x402 Payments"
              value={
                <span className="flex items-center gap-1 text-profit">
                  <Zap size={9} />
                  Enabled
                </span>
              }
            />
            <Row
              label="Risk Policy"
              value={
                <a
                  href="https://github.com/zehadkhan/alphaloop/blob/main/storage/policy_commitment.json"
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-accent hover:opacity-80"
                >
                  <FileCheck size={9} />
                  Signed
                  <ExternalLink size={8} />
                </a>
              }
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
