"use client";

import { useEffect, useState } from "react";

// Scans run every 30 min, so polling faster than this only re-reads the
// edge cache (/api/signals is cached for 15s).
const POLL_MS = 20_000;

type Signal = {
  id: number;
  symbol: string;
  direction: "LONG" | "SHORT";
  created_at: string;
  resolve_at: string;
  entry_price: number;
  funding_rate_raw: number;
  funding_interval_h: number;
  hold_min: number;
  risk_score: number;
  chart_analyzed: boolean;
  chart_confirmed: boolean;
  chart_confidence: number | null;
  tp: number | null;
  sl: number | null;
  rr_ratio: number | null;
  resolved: boolean;
  outcome: string | null;
  exit_price: number | null;
  realized_price_pct: number | null;
  net_pct: number | null;
};

type Bucket = {
  count: number;
  tp: number;
  sl: number;
  win_rate: number | null;
  avg_net: number | null;
};

type Stats = {
  days: number;
  total: number;
  pending: number;
  resolved: number;
  overall: Bucket;
  confirmed: Bucket;
};

const OUTCOME_LABEL: Record<string, { text: string; className: string }> = {
  tp_hit: { text: "TP hit", className: "text-accent bg-accent/10" },
  sl_hit: { text: "SL hit", className: "text-red-400 bg-red-400/10" },
  expired_favorable: { text: "Expired ↑", className: "text-accent-dim bg-accent/5" },
  expired_unfavorable: { text: "Expired ↓", className: "text-red-300 bg-red-400/5" },
  expired_flat: { text: "Expired flat", className: "text-muted bg-white/5" },
  no_data: { text: "No data", className: "text-muted bg-white/5" },
};

function fmtPrice(p: number | null) {
  if (p === null) return "—";
  const digits = p >= 100 ? 2 : p >= 1 ? 4 : 6;
  return `$${p.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function fmtPct(p: number | null, digits = 2) {
  if (p === null) return "—";
  return `${p > 0 ? "+" : ""}${p.toFixed(digits)}%`;
}

function timeAgo(iso: string, now: number) {
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function remaining(iso: string, now: number) {
  const mins = Math.max(0, Math.round((new Date(iso).getTime() - now) / 60000));
  return mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60}m left` : `${mins}m left`;
}

function StatCard({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: "up" | "down" }) {
  const color = tone === "up" ? "text-accent" : tone === "down" ? "text-red-400" : "text-foreground";
  return (
    <div className="rounded-xl border border-white/5 bg-surface p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-semibold ${color}`}>{value}</div>
      <div className="mt-1 text-xs text-muted">{sub}</div>
    </div>
  );
}

function SignalCard({ s, now }: { s: Signal; now: number }) {
  const open = !s.resolved;
  const outcome = s.outcome ? OUTCOME_LABEL[s.outcome] : null;
  const isLong = s.direction === "LONG";
  return (
    <li className="rounded-xl border border-white/5 bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <span className="font-mono text-lg font-semibold">{s.symbol}</span>
          <span
            className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
              isLong ? "bg-accent/15 text-accent" : "bg-red-400/15 text-red-400"
            }`}
          >
            {s.direction}
          </span>
          {s.chart_confirmed && (
            <span className="rounded-md border border-accent-dim/40 px-2 py-0.5 text-xs text-accent-dim">
              chart-confirmed {s.chart_confidence}%
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-sm">
          {open ? (
            <span className="flex items-center gap-1.5 rounded-md bg-yellow-300/10 px-2 py-0.5 text-yellow-200">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-yellow-200" />
              Open · {remaining(s.resolve_at, now)}
            </span>
          ) : (
            outcome && <span className={`rounded-md px-2 py-0.5 ${outcome.className}`}>{outcome.text}</span>
          )}
          <span className="text-muted">{timeAgo(s.created_at, now)}</span>
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-muted">Entry</dt>
          <dd className="font-mono">{fmtPrice(s.entry_price)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">TP / SL</dt>
          <dd className="font-mono">
            {s.tp !== null ? `${fmtPrice(s.tp)} / ${fmtPrice(s.sl)}` : `hold ~${s.hold_min}m`}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Funding</dt>
          <dd className="font-mono">
            {fmtPct(s.funding_rate_raw, 4)}/{s.funding_interval_h}h
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Net result</dt>
          <dd
            className={`font-mono font-semibold ${
              s.net_pct === null ? "text-muted" : s.net_pct > 0 ? "text-accent" : "text-red-400"
            }`}
          >
            {open ? "pending" : fmtPct(s.net_pct)}
          </dd>
        </div>
      </dl>
    </li>
  );
}

export default function LiveFeed() {
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [sigRes, statRes] = await Promise.all([
          fetch("/api/signals?limit=60"),
          fetch("/api/stats?days=30"),
        ]);
        if (!sigRes.ok || !statRes.ok) throw new Error("bad status");
        const [sigJson, statJson] = await Promise.all([sigRes.json(), statRes.json()]);
        if (cancelled) return;
        setSignals(sigJson.signals);
        setStats(statJson);
        setError(false);
        setUpdatedAt(Date.now());
      } catch {
        if (!cancelled) setError(true);
      }
    }

    load();
    const poll = setInterval(load, POLL_MS);
    const tick = setInterval(() => setNow(Date.now()), 30_000);
    return () => {
      cancelled = true;
      clearInterval(poll);
      clearInterval(tick);
    };
  }, []);

  const o = stats?.overall;
  const c = stats?.confirmed;

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm text-muted">
        <span className={`h-2 w-2 rounded-full ${error ? "bg-red-400" : "animate-pulse bg-accent"}`} />
        {error
          ? "Connection lost — retrying…"
          : updatedAt
            ? `Live · updated ${new Date(updatedAt).toLocaleTimeString()}`
            : "Connecting…"}
      </div>

      {stats && o && c && (
        <section className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label={`Avg net / trade (${stats.days}d)`}
            value={fmtPct(o.avg_net)}
            sub={`${o.count} resolved signals`}
            tone={o.avg_net === null ? undefined : o.avg_net > 0 ? "up" : "down"}
          />
          <StatCard
            label="Chart-confirmed net"
            value={fmtPct(c.avg_net)}
            sub={`${c.count} confirmed signals`}
            tone={c.avg_net === null ? undefined : c.avg_net > 0 ? "up" : "down"}
          />
          <StatCard
            label="TP vs SL"
            value={`${o.tp} / ${o.sl}`}
            sub={o.win_rate === null ? "no TP/SL exits yet" : `${o.win_rate.toFixed(0)}% hit TP first`}
          />
          <StatCard label="Open now" value={`${stats.pending}`} sub={`${stats.total} logged in ${stats.days}d`} />
        </section>
      )}

      {signals === null && !error && <p className="text-muted">Loading signals…</p>}
      {signals !== null && signals.length === 0 && (
        <p className="text-muted">No signals yet — the scanner checks the market every 30 minutes.</p>
      )}
      {signals && signals.length > 0 && (
        <ul className="flex flex-col gap-3">
          {signals.map((s) => (
            <SignalCard key={s.id} s={s} now={now} />
          ))}
        </ul>
      )}
    </div>
  );
}
