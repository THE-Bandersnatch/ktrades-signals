"use client";

import Link from "next/link";
import { fmtPct, useNow, usePoll, type ScannerStatus, type Signal, type Stats } from "../lib/signals";
import { ActiveTradeCard, RadarList, RadarSweep, ResultCard, ScannerPulse } from "./trades";

// Scans land every 30 min and the API is edge-cached for 15–60s, so polling
// faster than this would only re-read the cache.
const POLL_MS = 20_000;

function SectionTitle({ title, sub, action }: { title: string; sub?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="text-xl font-bold sm:text-2xl">{title}</h2>
        {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
      </div>
      {action}
    </div>
  );
}

export function LivePulse() {
  const { data: status } = usePoll<ScannerStatus>("/api/status", POLL_MS);
  const now = useNow();
  return <ScannerPulse status={status} now={now} />;
}

export default function LiveBoard({ telegramUrl }: { telegramUrl: string }) {
  const { data: open, error } = usePoll<{ signals: Signal[] }>("/api/signals?scope=trades&status=open&limit=12", POLL_MS);
  const { data: closed } = usePoll<{ signals: Signal[] }>("/api/signals?scope=trades&status=closed&limit=4", POLL_MS);
  const { data: status } = usePoll<ScannerStatus>("/api/status", POLL_MS);
  const { data: stats } = usePoll<Stats>("/api/stats?days=30", 60_000);
  const now = useNow();

  const active = open?.signals ?? [];
  const recent = closed?.signals ?? [];
  const radar = status?.radar ?? [];
  const confirmed = stats?.confirmed;

  return (
    <div className="flex flex-col gap-16">
      {/* Live trades */}
      <section id="live">
        <SectionTitle
          title="Live trades"
          sub="Chart-confirmed setups with entry, take-profit and stop-loss. Updates on its own."
          action={
            error ? <span className="text-xs text-rose-300">Reconnecting…</span> : null
          }
        />
        {open === null ? (
          <div className="h-48 animate-pulse rounded-3xl bg-surface" />
        ) : active.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2">
            {active.map((s) => (
              <ActiveTradeCard key={s.id} s={s} now={now} />
            ))}
          </div>
        ) : (
          <div className="rounded-3xl border border-dashed border-accent/20 bg-surface/60 px-6 py-10 text-center">
            <RadarSweep />
            <h3 className="mt-6 text-lg font-semibold">No open trades right now</h3>
            <p className="mx-auto mt-2 max-w-md text-sm text-muted">
              The scanner checks {status?.scanned_symbols ?? "hundreds of"} Binance futures every{" "}
              {status?.scan_interval_min ?? 30} minutes. The next trade appears here, and in
              Telegram, the moment it fires.
            </p>
            <a
              href={telegramUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-5 inline-block rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-background transition hover:brightness-110"
            >
              🔔 Get pinged on Telegram
            </a>
          </div>
        )}
      </section>

      {/* Radar */}
      {radar.length > 0 && (
        <section>
          <SectionTitle
            title="On the radar"
            sub="Most crowded liquid coins at the last scan. Extreme funding is where trades come from — these aren't signals yet."
          />
          <RadarList coins={radar} now={now} />
        </section>
      )}

      {/* Latest results */}
      <section>
        <SectionTitle
          title="Latest results"
          sub="Every trade is tracked to the end, wins and losses alike."
          action={
            <Link href="/history" className="text-sm font-semibold text-accent hover:underline">
              Full track record →
            </Link>
          }
        />
        {confirmed && confirmed.count > 0 && (
          <div className="mb-4 flex flex-wrap gap-x-6 gap-y-1 rounded-2xl border border-white/5 bg-surface px-4 py-3 text-sm">
            <span className="text-muted">Last 30 days</span>
            <span>
              <b className={confirmed.avg_net !== null && confirmed.avg_net > 0 ? "text-accent" : "text-rose-300"}>
                {fmtPct(confirmed.avg_net)}
              </b>{" "}
              <span className="text-muted">avg net / trade</span>
            </span>
            <span>
              <b>{confirmed.count}</b> <span className="text-muted">trades closed</span>
            </span>
            <span>
              <b>
                {confirmed.tp}/{confirmed.sl}
              </b>{" "}
              <span className="text-muted">TP / SL</span>
            </span>
          </div>
        )}
        {recent.length > 0 ? (
          <div className="grid gap-2 sm:grid-cols-2">
            {recent.map((s) => (
              <ResultCard key={s.id} s={s} now={now} />
            ))}
          </div>
        ) : (
          closed !== null && <p className="text-sm text-muted">No closed trades yet.</p>
        )}
      </section>
    </div>
  );
}
