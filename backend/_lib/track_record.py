#!/usr/bin/env python3
"""
track_record.py — log every signal the scanner surfaces, then check what
price actually did over the planned hold window, so "is this strategy any
good" has an answer grounded in outcomes instead of vibes.

Logs signals whether or not chart_analysis confirmed them, specifically so
confirmed vs. unconfirmed win rates can be compared later — that's the
only way to tell whether the technical-confirmation step is actually
adding value or just adding noise.
"""
import psycopg2.extras

from . import config
from . import db
from . import scanner


def log_signal(signal: dict, scan_id: int, chart_result: dict = None) -> None:
    """Insert one row. Never raises — a DB hiccup shouldn't block a scan."""
    try:
        analyzed = chart_result is not None
        confirmed = bool(chart_result and chart_result.get("confirmed"))
        entry = chart_result["entry"] if confirmed else signal["last_price"]

        conn = db.get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO signals (
                    scan_id, symbol, direction, entry_price,
                    funding_rate_raw, funding_rate_hourly, funding_interval_h,
                    persistence_ratio, payments_catchable, est_total_funding_earn,
                    risk_score, hold_min, chart_analyzed, chart_confirmed, chart_confidence,
                    tp, sl, rr_ratio, resolve_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    now() + (%s || ' minutes')::interval
                )
                """,
                (
                    scan_id, signal["symbol"], signal["direction"], entry,
                    signal["funding_rate_raw"], signal["funding_rate"], signal["funding_interval_h"],
                    signal["persistence_ratio"], signal["payments_catchable"], signal["est_total_funding_earn"],
                    signal["risk_score"], signal["hold_min"], analyzed, confirmed,
                    chart_result.get("confidence") if chart_result else None,
                    chart_result.get("tp") if confirmed else None,
                    chart_result.get("sl") if confirmed else None,
                    chart_result.get("rr_ratio") if confirmed else None,
                    signal["hold_min"],
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[TrackRecord] log_signal failed: {e}")


def _fetch_klines_range(symbol: str, start_ms: int, end_ms: int) -> list:
    data = scanner.api_get("/fapi/v1/klines", {
        "symbol": symbol, "interval": "1m",
        "startTime": start_ms, "endTime": end_ms, "limit": 1000,
    })
    if not data:
        return []
    return [{"high": float(k[2]), "low": float(k[3]), "close": float(k[4])} for k in data]


def _realized_pct(entry: float, exit_price: float, direction: str) -> float:
    raw = (exit_price - entry) / entry * 100
    return raw if direction == "LONG" else -raw


def _determine_outcome(row: dict) -> tuple:
    """(outcome, exit_price). Walks 1m candles chronologically; if a single
    candle touches both TP and SL, assumes SL hit first — the conservative
    read, since OHLC data alone can't order events within one candle."""
    symbol = row["symbol"] + "USDT"
    start_ms = int(row["created_at"].timestamp() * 1000)
    end_ms = int(row["resolve_at"].timestamp() * 1000)
    candles = _fetch_klines_range(symbol, start_ms, end_ms)

    if not candles:
        return "no_data", None

    entry = float(row["entry_price"])
    tp = float(row["tp"]) if row["tp"] is not None else None
    sl = float(row["sl"]) if row["sl"] is not None else None
    direction = row["direction"]

    for c in candles:
        hit_tp = tp is not None and (
            (direction == "LONG" and c["high"] >= tp) or (direction == "SHORT" and c["low"] <= tp)
        )
        hit_sl = sl is not None and (
            (direction == "LONG" and c["low"] <= sl) or (direction == "SHORT" and c["high"] >= sl)
        )
        if hit_sl:
            return "sl_hit", sl
        if hit_tp:
            return "tp_hit", tp

    exit_price = candles[-1]["close"]
    move_pct = _realized_pct(entry, exit_price, direction)
    if move_pct > 0.05:
        return "expired_favorable", exit_price
    elif move_pct < -0.05:
        return "expired_unfavorable", exit_price
    return "expired_flat", exit_price


def resolve_pending_signals() -> dict:
    """Resolve every signal whose hold window has elapsed. Never raises."""
    counts = {"resolved": 0, "tp_hit": 0, "sl_hit": 0, "expired": 0, "no_data": 0}
    try:
        conn = db.get_conn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT id, symbol, direction, entry_price, tp, sl, created_at, resolve_at "
                "FROM signals WHERE NOT resolved AND resolve_at <= now()"
            )
            pending = cur.fetchall()

            for row in pending:
                outcome, exit_price = _determine_outcome(row)
                realized_pct = (
                    _realized_pct(float(row["entry_price"]), exit_price, row["direction"])
                    if exit_price is not None else None
                )
                cur.execute(
                    "UPDATE signals SET resolved=true, resolved_at=now(), "
                    "outcome=%s, exit_price=%s, realized_price_pct=%s WHERE id=%s",
                    (outcome, exit_price, realized_pct, row["id"]),
                )
                counts["resolved"] += 1
                if outcome == "tp_hit":
                    counts["tp_hit"] += 1
                elif outcome == "sl_hit":
                    counts["sl_hit"] += 1
                elif outcome == "no_data":
                    counts["no_data"] += 1
                else:
                    counts["expired"] += 1

            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[TrackRecord] resolve_pending_signals failed: {e}")
    return counts


def get_stats(days: int = 30) -> dict:
    conn = db.get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT chart_analyzed, chart_confirmed, resolved, outcome, realized_price_pct FROM signals "
            "WHERE created_at >= now() - (%s || ' days')::interval",
            (days,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    resolved_rows = [r for r in rows if r["resolved"]]

    def summarize(subset):
        tp = sum(1 for r in subset if r["outcome"] == "tp_hit")
        sl = sum(1 for r in subset if r["outcome"] == "sl_hit")
        decided = tp + sl
        win_rate = (tp / decided * 100) if decided else None
        pct_values = [float(r["realized_price_pct"]) for r in subset if r["realized_price_pct"] is not None]
        avg_pct = sum(pct_values) / len(pct_values) if pct_values else None
        return {"count": len(subset), "tp": tp, "sl": sl, "win_rate": win_rate, "avg_pct": avg_pct}

    return {
        "days": days,
        "total": len(rows),
        "pending": sum(1 for r in rows if not r["resolved"]),
        "resolved": len(resolved_rows),
        "overall": summarize(resolved_rows),
        "confirmed": summarize([r for r in resolved_rows if r["chart_confirmed"]]),
        "rejected": summarize([r for r in resolved_rows if r["chart_analyzed"] and not r["chart_confirmed"]]),
        "not_analyzed": summarize([r for r in resolved_rows if not r["chart_analyzed"]]),
    }
