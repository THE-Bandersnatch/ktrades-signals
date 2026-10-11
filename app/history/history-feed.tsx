"use client";

import { useState } from "react";
import { CoinAvatar } from "../components/trades";
import {
  OUTCOME,
  fmtPct,
  fmtPrice,
  timeAgo,
  useNow,
  usePoll,
  type Bucket,
  type Signal,
  type Stats,
} from "../lib/signals";

const PAGE = 30;

function StatCard({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: "up" | "down" }) {
  const color = tone === "up" ? "text-accent" : tone === "down" ? "text-rose-300" : "text-foreground";
  return (
    <div className="rounded-3xl border border-white/5 bg-surface p-4">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-bold ${color}`}>{value}</div>
      <div className="mt-1 text-xs text-muted">{sub}</div>
    </div>
  );
}

function tone(b: Bucket | undefined) {
  if (!b || b.avg_net === null) return undefined;
  return b.avg_net > 0 ? "up" : "down";
}

function Row({ s, now }: { s: Signal; now: number }) {
  const o = s.outcome ? OUTCOME[s.outcome] : null;
  const open = !s.resolved;
  return (
    <li className="rounded-2xl border border-white/5 bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <CoinAvatar symbol={s.symbol} size={34} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono font-bold">{s.symbol}</span>
            <span className={`text-xs font-bold ${s.direction === "LONG" ? "text-accent" : "text-rose-300"}`}>
              {s.direction === "LONG" ? "▲ LONG" : "▼ SHORT"}
            </span>
            {s.chart_confirmed ? (
              <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] text-accent">trade</span>
            ) : (
              <span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] text-muted">watchlist</span>
            )}
          </div>
          <div className="text-xs text-muted">
            {timeAgo(s.created_at, now)} · entry {fmtPrice(s.entry_price)} · funding{" "}
            {fmtPct(s.funding_rate_raw, 3)}/{s.funding_interval_h}h
          </div>
        </div>
        <div className="text-right">
          <div
            className={`font-mono text-sm font-bold ${
              open || s.net_pct === null ? "text-muted" : s.net_pct > 0 ? "text-accent" : "text-rose-300"
            }`}
          >
            {open ? "open" : fmtPct(s.net_pct)}
          </div>
          <div className="text-[11px] text-muted">{open ? "in progress" : o ? `${o.emoji} ${o.text}` : ""}</div>
        </div>
      </div>
    </li>
  );
}

export default function HistoryFeed() {
  const [scope, setScope] = useState<"trades" | "all">("trades");
  const [limit, setLimit] = useState(PAGE);
  const now = useNow(30_000);
  const { data: stats } = usePoll<Stats>("/api/stats?days=30", 60_000);
  const { data, error } = usePoll<{ signals: Signal[] }>(
    `/api/signals?limit=${limit}${scope === "trades" ? "&scope=trades" : ""}`,
    30_000,
  );

  const c = stats?.confirmed;
  const o = stats?.overall;
  const rows = data?.signals ?? [];

  return (
    <div className="mt-8">
      {stats && c && o && (
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label="Trades · avg net"
            value={fmtPct(c.avg_net)}
            sub={`${c.count} trades closed in ${stats.days}d`}
            tone={tone(c)}
          />
          <StatCard
            label="Trades · TP vs SL"
            value={`${c.tp} / ${c.sl}`}
            sub={c.win_rate === null ? "no exits yet" : `${c.win_rate.toFixed(0)}% reached TP first`}
          />
          <StatCard
            label="All signals · avg net"
            value={fmtPct(o.avg_net)}
            sub={`${o.count} signals incl. watchlist`}
            tone={tone(o)}
          />
          <StatCard label="Open now" value={`${stats.pending}`} sub={`${stats.total} logged in ${stats.days}d`} />
        </section>
      )}

      <p className="mt-4 text-xs text-muted">
        A few large moves account for much of the average. The typical trade is much closer to
        zero, so treat this as a running record, not a promise.
      </p>

      <div className="mt-8 flex items-center gap-2">
        {(["trades", "all"] as const).map((k) => (
          <button
            key={k}
            onClick={() => {
              setScope(k);
              setLimit(PAGE);
            }}
            className={`rounded-full px-4 py-1.5 text-sm font-semibold transition ${
              scope === k ? "bg-accent text-background" : "bg-surface text-muted hover:text-foreground"
            }`}
          >
            {k === "trades" ? "Trades" : "All signals"}
          </button>
        ))}
        {error && <span className="ml-auto text-xs text-rose-300">Reconnecting…</span>}
      </div>
      <p className="mt-2 text-xs text-muted">
        {scope === "trades"
          ? "Chart-confirmed setups posted with entry, take-profit and stop-loss."
          : "Includes watchlist signals: extreme funding without chart confirmation, held for the funding window and posted without a stop."}
      </p>

      {data === null && !error && <div className="mt-4 h-40 animate-pulse rounded-3xl bg-surface" />}
      {data !== null && rows.length === 0 && <p className="mt-6 text-muted">Nothing here yet.</p>}
      <ul className="mt-4 flex flex-col gap-2">
        {rows.map((s) => (
          <Row key={s.id} s={s} now={now} />
        ))}
      </ul>
      {rows.length >= limit && limit < 200 && (
        <div className="mt-6 text-center">
          <button
            onClick={() => setLimit((l) => Math.min(200, l + PAGE))}
            className="rounded-full border border-white/10 px-5 py-2 text-sm font-semibold transition hover:border-accent/40 hover:text-accent"
          >
            Load more
          </button>
        </div>
      )}
    </div>
  );
}
