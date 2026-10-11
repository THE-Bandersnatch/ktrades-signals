"use client";

import { useEffect, useState } from "react";
import {
  OUTCOME,
  coinHue,
  countdown,
  fmtPct,
  fmtPrice,
  timeAgo,
  type RadarCoin,
  type ScannerStatus,
  type Signal,
} from "../lib/signals";

export function CoinAvatar({ symbol, size = 44 }: { symbol: string; size?: number }) {
  const hue = coinHue(symbol);
  return (
    <span
      aria-hidden
      className="grid shrink-0 place-items-center rounded-full font-mono font-bold"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.3,
        color: `hsl(${hue} 90% 80%)`,
        background: `radial-gradient(circle at 30% 25%, hsl(${hue} 70% 32%), hsl(${hue} 60% 14%))`,
        boxShadow: `0 0 0 1px hsl(${hue} 60% 40% / 0.5), 0 0 24px -6px hsl(${hue} 80% 50% / 0.6)`,
      }}
    >
      {symbol.slice(0, 3)}
    </span>
  );
}

function DirectionPill({ direction }: { direction: "LONG" | "SHORT" }) {
  const long = direction === "LONG";
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 text-xs font-bold tracking-wide ${
        long ? "bg-accent/15 text-accent" : "bg-rose-400/15 text-rose-300"
      }`}
    >
      {long ? "▲ LONG" : "▼ SHORT"}
    </span>
  );
}

/**
 * Live mark price from Binance's public futures API, straight from the
 * visitor's browser. Binance blocks some regions, so this fails silently and
 * the card just shows the plan without a live marker.
 */
function useMarkPrice(symbol: string, enabled: boolean) {
  const [price, setPrice] = useState<number | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(`https://fapi.binance.com/fapi/v1/premiumIndex?symbol=${symbol}USDT`);
        if (!res.ok) return;
        const json = await res.json();
        const p = parseFloat(json.markPrice);
        if (!cancelled && Number.isFinite(p)) setPrice(p);
      } catch {
        /* region-blocked or offline — keep the static view */
      }
    }
    load();
    const id = setInterval(load, 10_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol, enabled]);
  return price;
}

/** SL ← entry → TP track with a live price marker. */
function PriceTrack({ s, mark }: { s: Signal; mark: number | null }) {
  if (s.tp === null || s.sl === null) return null;
  const long = s.direction === "LONG";
  // Normalise so SL is always left (0) and TP always right (1).
  const pos = (p: number) => {
    const t = long ? (p - s.sl!) / (s.tp! - s.sl!) : (s.sl! - p) / (s.sl! - s.tp!);
    return Math.min(1, Math.max(0, t));
  };
  const entryPos = pos(s.entry_price);
  const markPos = mark !== null ? pos(mark) : null;
  const pnl = mark !== null ? ((mark - s.entry_price) / s.entry_price) * 100 * (long ? 1 : -1) : null;

  return (
    <div className="mt-4">
      <div className="relative h-2.5 rounded-full bg-gradient-to-r from-rose-500/50 via-white/10 to-accent/60">
        <span
          className="absolute top-1/2 h-4 w-0.5 -translate-y-1/2 rounded bg-white/70"
          style={{ left: `${entryPos * 100}%` }}
          title="Entry"
        />
        {markPos !== null && (
          <span
            className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-yellow-200 shadow-[0_0_12px_2px_rgba(253,230,138,0.6)] transition-[left] duration-700"
            style={{ left: `${markPos * 100}%` }}
            title="Live price"
          />
        )}
      </div>
      <div className="mt-2 flex flex-wrap justify-between gap-x-2 font-mono text-[11px] text-muted">
        <span>SL {fmtPrice(s.sl)}</span>
        <span className="text-foreground/80">Entry {fmtPrice(s.entry_price)}</span>
        <span>TP {fmtPrice(s.tp)}</span>
      </div>
      {pnl !== null && (
        <div className="mt-2 text-xs text-muted">
          Live price {fmtPrice(mark)} ·{" "}
          <span className={pnl >= 0 ? "text-accent" : "text-rose-300"}>{fmtPct(pnl)} unrealized</span>
        </div>
      )}
    </div>
  );
}

export function ActiveTradeCard({ s, now }: { s: Signal; now: number }) {
  const mark = useMarkPrice(s.symbol, true);
  const start = new Date(s.created_at).getTime();
  const end = new Date(s.resolve_at).getTime();
  const progress = Math.min(1, Math.max(0, (now - start) / (end - start)));

  return (
    <article className="glow-card relative overflow-hidden rounded-3xl border border-accent/25 bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <CoinAvatar symbol={s.symbol} />
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xl font-bold">{s.symbol}</span>
              <DirectionPill direction={s.direction} />
            </div>
            <div className="mt-0.5 text-xs text-muted">
              opened {timeAgo(s.created_at, now)} · {s.chart_confidence}% chart confidence
            </div>
          </div>
        </div>
        <span className="flex items-center gap-1.5 rounded-full bg-accent/10 px-2.5 py-1 text-xs font-semibold text-accent">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
          </span>
          LIVE
        </span>
      </div>

      <PriceTrack s={s} mark={mark} />

      <div className="mt-4 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-2xl bg-white/[0.03] px-2 py-2">
          <div className="text-[10px] uppercase tracking-wider text-muted">Funding</div>
          <div className="font-mono text-sm">
            {fmtPct(s.funding_rate_raw, 3)}
            <span className="text-muted">/{s.funding_interval_h}h</span>
          </div>
        </div>
        <div className="rounded-2xl bg-white/[0.03] px-2 py-2">
          <div className="text-[10px] uppercase tracking-wider text-muted">Reward:Risk</div>
          <div className="font-mono text-sm">1:{s.rr_ratio ?? "—"}</div>
        </div>
        <div className="rounded-2xl bg-white/[0.03] px-2 py-2">
          <div className="text-[10px] uppercase tracking-wider text-muted">Closes in</div>
          <div className="font-mono text-sm">{countdown(end - now)}</div>
        </div>
      </div>

      <div className="mt-4 h-1 overflow-hidden rounded-full bg-white/5">
        <div className="h-full rounded-full bg-accent/70 transition-[width] duration-1000" style={{ width: `${progress * 100}%` }} />
      </div>
    </article>
  );
}

export function ResultCard({ s, now }: { s: Signal; now: number }) {
  const o = s.outcome ? OUTCOME[s.outcome] : null;
  const net = s.net_pct;
  const win = net !== null && net > 0;
  return (
    <article className="flex items-center gap-3 rounded-2xl border border-white/5 bg-surface px-4 py-3">
      <CoinAvatar symbol={s.symbol} size={36} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono font-bold">{s.symbol}</span>
          <DirectionPill direction={s.direction} />
        </div>
        <div className="truncate text-xs text-muted">
          {o ? `${o.emoji} ${o.text}` : "Resolved"} · {timeAgo(s.resolved_at ?? s.resolve_at, now)}
        </div>
      </div>
      <div
        className={`rounded-xl px-3 py-1.5 font-mono text-sm font-bold ${
          net === null ? "bg-white/5 text-muted" : win ? "bg-accent/15 text-accent" : "bg-rose-400/15 text-rose-300"
        }`}
      >
        {fmtPct(net)}
      </div>
    </article>
  );
}

export function ScannerPulse({ status, now }: { status: ScannerStatus | null; now: number }) {
  if (!status) {
    return <span className="text-sm text-muted">Connecting to scanner…</span>;
  }
  if (!status.last_scan) {
    return <span className="text-sm text-muted">Scanner warming up — first scan lands shortly.</span>;
  }
  const last = new Date(status.last_scan).getTime();
  const next = last + status.scan_interval_min * 60_000;
  const due = next - now;
  return (
    <div className="inline-flex flex-wrap items-center justify-center gap-x-3 gap-y-1 rounded-full border border-white/10 bg-surface/80 px-4 py-2 text-sm backdrop-blur">
      <span className="flex items-center gap-2">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent" />
        </span>
        <span className="font-semibold">Scanner live</span>
      </span>
      <span className="text-muted">
        {status.scanned_symbols ?? 0} coins checked {timeAgo(status.last_scan, now)}
      </span>
      {/* The scheduler can run late; once a scan is overdue, a countdown
          would be a promise we can't keep, so drop it. */}
      {due > 0 ? (
        <span className="font-mono text-accent">next scan in {countdown(due)}</span>
      ) : due > -10 * 60_000 ? (
        <span className="font-mono text-accent">scanning any moment…</span>
      ) : null}
    </div>
  );
}

export function RadarSweep() {
  return (
    <div className="radar relative mx-auto h-36 w-36 rounded-full border border-accent/20">
      <div className="absolute inset-4 rounded-full border border-accent/15" />
      <div className="absolute inset-10 rounded-full border border-accent/10" />
      <div className="radar-sweep absolute inset-0 rounded-full" />
      <span className="absolute left-[62%] top-[30%] h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
      <span className="absolute left-[28%] top-[58%] h-1 w-1 animate-pulse rounded-full bg-accent/70 [animation-delay:700ms]" />
    </div>
  );
}

export function RadarList({ coins, now }: { coins: RadarCoin[]; now: number }) {
  if (coins.length === 0) return null;
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {coins.map((c) => {
        const longsPaid = c.funding_rate_pct < 0;
        return (
          <li key={c.symbol} className="flex items-center gap-3 rounded-2xl border border-white/5 bg-surface px-3 py-2.5">
            <CoinAvatar symbol={c.symbol} size={32} />
            <div className="min-w-0 flex-1">
              <div className="font-mono text-sm font-bold">{c.symbol}</div>
              <div className="text-xs text-muted">
                {longsPaid ? "shorts crowded" : "longs crowded"} · ${c.volume_m}M vol
              </div>
            </div>
            <div className="text-right">
              <div className={`font-mono text-sm ${longsPaid ? "text-accent" : "text-rose-300"}`}>
                {fmtPct(c.funding_rate_pct, 3)}/h
              </div>
              <div className="font-mono text-[11px] text-muted">pays in {countdown(c.next_funding - now)}</div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
