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
    return [
        {"open_time": int(k[0]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])}
        for k in data
    ]


def _realized_pct(entry: float, exit_price: float, direction: str) -> float:
    raw = (exit_price - entry) / entry * 100
    return raw if direction == "LONG" else -raw


def _walk(candles: list, direction: str, tp, sl, end_ms: int) -> tuple:
    """(outcome, exit_price, exit_ms) for one side of a trade. Walks 1m
    candles chronologically; if a single candle touches both TP and SL,
    assumes SL hit first — the conservative read for whichever side is
    being measured, since OHLC data alone can't order events within one
    candle. Measuring the inverse with its own swapped levels (rather than
    flipping the original's result) is what keeps that rule from silently
    handing every ambiguous candle to the inverse as a win."""
    for c in candles:
        hit_tp = tp is not None and (
            (direction == "LONG" and c["high"] >= tp) or (direction == "SHORT" and c["low"] <= tp)
        )
        hit_sl = sl is not None and (
            (direction == "LONG" and c["low"] <= sl) or (direction == "SHORT" and c["high"] >= sl)
        )
        if hit_sl:
            return "sl_hit", sl, c["open_time"] + 60_000
        if hit_tp:
            return "tp_hit", tp, c["open_time"] + 60_000
    return None, candles[-1]["close"], end_ms


def _expired_outcome(move_pct: float) -> str:
    if move_pct > 0.05:
        return "expired_favorable"
    elif move_pct < -0.05:
        return "expired_unfavorable"
    return "expired_flat"


def _funding_pct(symbol: str, direction: str, start_ms: int, end_ms: int):
    """Funding actually paid (+) or charged (-) to a position held from
    start_ms to end_ms, as % of notional. Positive rate: longs pay shorts.
    Returns None if Binance didn't answer, so a missing lookup is never
    mistaken for "no funding was due"."""
    if end_ms <= start_ms:
        return 0.0
    data = scanner.api_get("/fapi/v1/fundingRate", {
        "symbol": symbol, "startTime": start_ms + 1, "endTime": end_ms, "limit": 100,
    })
    if data is None:
        return None
    total_rate = sum(float(d["fundingRate"]) for d in data if start_ms < int(d["fundingTime"]) <= end_ms)
    return (-total_rate if direction == "LONG" else total_rate) * 100


def _evaluate(row: dict) -> dict:
    """Resolve a signal and its inverse against the same candles. Returns
    the column values to store; outcome is "no_data" if Binance returned
    nothing for the window."""
    symbol = row["symbol"] + "USDT"
    start_ms = int(row["created_at"].timestamp() * 1000)
    end_ms = int(row["resolve_at"].timestamp() * 1000)
    candles = _fetch_klines_range(symbol, start_ms, end_ms)
    if not candles:
        return {"outcome": "no_data"}

    entry = float(row["entry_price"])
    tp = float(row["tp"]) if row["tp"] is not None else None
    sl = float(row["sl"]) if row["sl"] is not None else None
    direction = row["direction"]
    inv_direction = "SHORT" if direction == "LONG" else "LONG"

    result = {}
    # The inverse takes the opposite side with TP and SL swapped: the
    # original's stop is where the inverse takes profit, and vice versa.
    for prefix, side, side_tp, side_sl in (("", direction, tp, sl), ("inv_", inv_direction, sl, tp)):
        outcome, exit_price, exit_ms = _walk(candles, side, side_tp, side_sl, end_ms)
        move = _realized_pct(entry, exit_price, side)
        funding = _funding_pct(symbol, side, start_ms, exit_ms)
        result[prefix + "outcome"] = outcome or _expired_outcome(move)
        result[prefix + "exit_price"] = exit_price
        result[prefix + "realized_price_pct"] = move
        result[prefix + "funding_pct"] = funding
        result[prefix + "net_pct"] = (
            move + funding - config.ROUND_TRIP_FEE_PCT if funding is not None else None
        )
    return result


_ROW_COLUMNS = "id, symbol, direction, entry_price, tp, sl, created_at, resolve_at"
_NEW_FIELDS = (
    "funding_pct", "net_pct", "inv_outcome", "inv_exit_price",
    "inv_realized_price_pct", "inv_funding_pct", "inv_net_pct",
)


def resolve_pending_signals() -> dict:
    """Resolve every signal whose hold window has elapsed, then backfill a
    bounded batch of older resolved rows that predate the net/inverse
    columns. Never raises."""
    counts = {"resolved": 0, "tp_hit": 0, "sl_hit": 0, "expired": 0, "no_data": 0, "backfilled": 0}
    try:
        conn = db.get_conn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(f"SELECT {_ROW_COLUMNS} FROM signals WHERE NOT resolved AND resolve_at <= now()")
            for row in cur.fetchall():
                r = _evaluate(row)
                outcome = r["outcome"]
                cur.execute(
                    "UPDATE signals SET resolved=true, resolved_at=now(), outcome=%s, exit_price=%s, "
                    "realized_price_pct=%s, " + ", ".join(f"{f}=%s" for f in _NEW_FIELDS) + " WHERE id=%s",
                    (outcome, r.get("exit_price"), r.get("realized_price_pct"),
                     *(r.get(f) for f in _NEW_FIELDS), row["id"]),
                )
                counts["resolved"] += 1
                if outcome in ("tp_hit", "sl_hit", "no_data"):
                    counts[outcome] += 1
                else:
                    counts["expired"] += 1
            conn.commit()

            # Backfill only the new fields — the original outcome columns
            # were already settled and are left exactly as recorded.
            cur.execute(
                f"SELECT {_ROW_COLUMNS} FROM signals "
                "WHERE resolved AND net_pct IS NULL AND outcome <> 'no_data' ORDER BY id LIMIT %s",
                (config.BACKFILL_BATCH,),
            )
            for row in cur.fetchall():
                r = _evaluate(row)
                if r["outcome"] == "no_data" or r.get("net_pct") is None:
                    continue
                cur.execute(
                    "UPDATE signals SET " + ", ".join(f"{f}=%s" for f in _NEW_FIELDS) + " WHERE id=%s",
                    (*(r.get(f) for f in _NEW_FIELDS), row["id"]),
                )
                counts["backfilled"] += 1
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[TrackRecord] resolve_pending_signals failed: {e}")
    return counts


def _summarize(subset: list, prefix: str = "") -> dict:
    """Stats for one side. win_rate is TP vs SL only; avg_net is the number
    that decides whether a side makes money — it weighs win size against
    loss size and includes fees and funding."""
    outcomes = [r[prefix + "outcome"] for r in subset]
    tp = outcomes.count("tp_hit")
    sl = outcomes.count("sl_hit")
    decided = tp + sl

    def avg(col):
        vals = [float(r[col]) for r in subset if r[col] is not None]
        return (sum(vals) / len(vals)) if vals else None

    return {
        "count": len(subset),
        "tp": tp,
        "sl": sl,
        "win_rate": (tp / decided * 100) if decided else None,
        "avg_pct": avg(prefix + "realized_price_pct"),
        "avg_net": avg(prefix + "net_pct"),
        "net_count": sum(1 for r in subset if r[prefix + "net_pct"] is not None),
    }


def get_stats(days: int = 30) -> dict:
    conn = db.get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT chart_analyzed, chart_confirmed, resolved, outcome, realized_price_pct, net_pct, "
            "inv_outcome, inv_realized_price_pct, inv_net_pct FROM signals "
            "WHERE created_at >= now() - (%s || ' days')::interval",
            (days,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    resolved_rows = [r for r in rows if r["resolved"] and r["outcome"] != "no_data"]
    buckets = {
        "overall": resolved_rows,
        "confirmed": [r for r in resolved_rows if r["chart_confirmed"]],
        "rejected": [r for r in resolved_rows if r["chart_analyzed"] and not r["chart_confirmed"]],
        "not_analyzed": [r for r in resolved_rows if not r["chart_analyzed"]],
    }

    stats = {
        "days": days,
        "total": len(rows),
        "pending": sum(1 for r in rows if not r["resolved"]),
        "resolved": len(resolved_rows),
        "fee_pct": config.ROUND_TRIP_FEE_PCT,
    }
    for name, subset in buckets.items():
        stats[name] = _summarize(subset)
        stats["inverse_" + name] = _summarize(subset, "inv_")
    return stats


def get_recent_signals(limit: int = 50) -> list:
    """Newest signals first, shaped for the public live feed."""
    conn = db.get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, symbol, direction, created_at, entry_price, funding_rate_raw, "
            "funding_interval_h, persistence_ratio, risk_score, hold_min, chart_analyzed, "
            "chart_confirmed, chart_confidence, tp, sl, rr_ratio, resolve_at, resolved, "
            "outcome, exit_price, realized_price_pct, net_pct "
            "FROM signals ORDER BY created_at DESC, id DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        item = {}
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            elif v is not None and k not in ("id", "risk_score", "hold_min", "funding_interval_h",
                                             "chart_confidence", "symbol", "direction", "outcome",
                                             "chart_analyzed", "chart_confirmed", "resolved"):
                item[k] = float(v)
            else:
                item[k] = v
        out.append(item)
    return out
