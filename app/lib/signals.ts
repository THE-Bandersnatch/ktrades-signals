"use client";

import { useEffect, useState } from "react";

export type Signal = {
  id: number;
  symbol: string;
  direction: "LONG" | "SHORT";
  created_at: string;
  resolve_at: string;
  resolved_at: string | null;
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

export type Bucket = {
  count: number;
  tp: number;
  sl: number;
  win_rate: number | null;
  avg_net: number | null;
};

export type Stats = {
  days: number;
  total: number;
  pending: number;
  resolved: number;
  fee_pct: number;
  overall: Bucket;
  confirmed: Bucket;
  rejected: Bucket;
  not_analyzed: Bucket;
};

export type RadarCoin = {
  symbol: string;
  funding_rate_pct: number;
  volume_m: number;
  next_funding: number;
};

export type ScannerStatus = {
  last_scan: string | null;
  scan_interval_min: number;
  scans_24h: number;
  api_ok?: boolean;
  scanned_symbols?: number;
  signals?: number;
  confirmed?: number;
  radar: RadarCoin[];
};

export const OUTCOME: Record<string, { text: string; emoji: string; tone: "win" | "loss" | "flat" }> = {
  tp_hit: { text: "Take-profit hit", emoji: "🎯", tone: "win" },
  sl_hit: { text: "Stop-loss hit", emoji: "🛑", tone: "loss" },
  // Expiry labels describe the exit, not the result: net also includes
  // funding, so a trade closed flat on price can still be up.
  expired_favorable: { text: "Closed at time limit", emoji: "⏱", tone: "win" },
  expired_unfavorable: { text: "Closed at time limit", emoji: "⏱", tone: "loss" },
  expired_flat: { text: "Closed at time limit", emoji: "⏱", tone: "flat" },
  no_data: { text: "No data", emoji: "·", tone: "flat" },
};

/** Polls a JSON endpoint. Keeps the last good payload on a failed poll. */
export function usePoll<T>(url: string, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(String(res.status));
        const json = (await res.json()) as T;
        if (!cancelled) {
          setData(json);
          setError(false);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    }
    load();
    const id = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [url, intervalMs]);

  return { data, error };
}

/** A clock that re-renders every `stepMs`, for countdowns. */
export function useNow(stepMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), stepMs);
    return () => clearInterval(id);
  }, [stepMs]);
  return now;
}

export function fmtPrice(p: number | null) {
  if (p === null) return "—";
  const digits = p >= 100 ? 2 : p >= 1 ? 4 : 6;
  return `$${p.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function fmtPct(p: number | null | undefined, digits = 2) {
  if (p === null || p === undefined) return "—";
  return `${p > 0 ? "+" : ""}${p.toFixed(digits)}%`;
}

export function timeAgo(iso: string, now: number) {
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function countdown(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Stable hue per coin so each ticker gets its own avatar colour. */
export function coinHue(symbol: string) {
  let h = 0;
  for (const ch of symbol) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}
