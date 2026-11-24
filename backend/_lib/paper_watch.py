"""
paper_watch.py — hosted paper-trade watchers, run by /api/watch about once a minute.

PAPER ONLY. Reads public Binance futures candles, records paper trades in
Postgres, and sends alerts to the admin chats (never the public channel).
It never places orders.

Two rules are tested:
  scalp_1m  ETHUSDT. Entry when 1m RSI(14) crosses below 30. Exit at +0.15% target,
            -0.25% stop, or the close 5 candles later. 0.08% round-trip fees.
            30-day replay (2026-11-24): -0.075%/trade after fees.
  swing_4h  22 coins. Entry when 4h RSI crosses up through 50 with close > EMA200.
            Stop = lowest low of the last 10 candles (skipped if >15% away).
            Exit at the stop or when 4h RSI < 30. No target. 0.10% fees.
            ~500-day replay: -39R overall, +45R in the more recent half.

Each call catches up on every candle closed since the last call, so a missed
trigger delays alerts but does not lose trades. A Postgres advisory lock stops
overlapping calls from processing the same candles twice.
"""
import datetime as dt
import html
import json
import time

import psycopg2.extras
import requests

from . import config
from . import db
from . import telegram

FAPI = config.BASE_URL
LOCK_ID = 7_412_001

SCALP = dict(symbol="ETHUSDT", rsi_entry=30, tp=0.15, sl=0.25, hold=5, fee=0.08)
SWING = dict(
    symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT",
             "LINKUSDT", "AVAXUSDT", "LTCUSDT", "DOTUSDT", "TRXUSDT", "BCHUSDT", "UNIUSDT",
             "AAVEUSDT", "ATOMUSDT", "ETCUSDT", "FILUSDT", "HYPEUSDT", "ZECUSDT", "NEARUSDT",
             "SUIUSDT"],
    rsi_entry=50, rsi_exit=30, ema=200, stop_lookback=10, max_risk=15.0, fee=0.10,
)
FOUR_H_MS = 4 * 3600 * 1000


# ── indicators / data ────────────────────────────
def rsi_series(c, n=14):
    out = [50.0] * len(c); ag = al = 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]; g, l = max(d, 0.0), max(-d, 0.0)
        if i <= n: ag += g / n; al += l / n
        else:      ag = (ag * (n - 1) + g) / n; al = (al * (n - 1) + l) / n
        if i >= n: out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def ema_series(a, n):
    k = 2 / (n + 1); o = [a[0]]
    for v in a[1:]: o.append(v * k + o[-1] * (1 - k))
    return o


def closed_klines(symbol, interval, limit):
    r = requests.get(f"{FAPI}/fapi/v1/klines",
                     params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    r.raise_for_status()
    now = int(time.time() * 1000)
    # (open_time_ms, high, low, close)
    return [(int(k[0]), float(k[2]), float(k[3]), float(k[4])) for k in r.json() if int(k[6]) < now]


def ts(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)


def fmt(px):
    return f"{px:,.2f}" if px >= 100 else f"{px:.4g}"


# ── state ────────────────────────────────────────
DEFAULT_ALERTS = {"scalp": True, "swing": True}


def _get(cur, key, default):
    cur.execute("SELECT value FROM paper_watch_state WHERE key = %s", (key,))
    row = cur.fetchone()
    return row[0] if row else default


def _put(cur, key, value):
    cur.execute(
        "INSERT INTO paper_watch_state (key, value, updated_at) VALUES (%s, %s, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (key, json.dumps(value)),
    )


def _log_trade(cur, strategy, symbol, pos, exit_ms, exit_px, reason, ret, r=None):
    cur.execute(
        "INSERT INTO paper_trades (strategy, symbol, entry_time, entry, stop, target, "
        "exit_time, exit, reason, ret_pct, r) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (strategy, symbol, ts(pos["t"]), pos["entry"], pos.get("stop"), pos.get("target"),
         ts(exit_ms), exit_px, reason, round(ret, 4), None if r is None else round(r, 3)),
    )


# ── scalp_1m ─────────────────────────────────────
def _run_scalp(cur, out):
    p = SCALP
    st = _get(cur, "scalp", {})
    ks = closed_klines(p["symbol"], "1m", 300)
    t = [k[0] for k in ks]; hi = [k[1] for k in ks]; lo = [k[2] for k in ks]; c = [k[3] for k in ks]
    rsi = rsi_series(c)
    last = st.get("last_bar")
    if last is None:
        _put(cur, "scalp", {"last_bar": t[-1], "open": None}); return
    pos = st.get("open")
    for i in range(50, len(ks)):
        if t[i] <= last: continue
        if pos:
            pos["bars"] += 1
            px = reason = None
            if lo[i] <= pos["stop"]:     px, reason = pos["stop"], "stop"
            elif hi[i] >= pos["target"]: px, reason = pos["target"], "target"
            elif pos["bars"] >= p["hold"]: px, reason = c[i], "time"
            if px is not None:
                gross = (px / pos["entry"] - 1) * 100
                net = gross - p["fee"]
                _log_trade(cur, "scalp_1m", p["symbol"], pos, t[i], px, reason, net)
                out.append(("scalp", f"📝 PAPER EXIT {p['symbol']} ({reason}) {gross:+.3f}% gross, "
                                     f"{net:+.3f}% after fees"))
                pos = None
        elif rsi[i] < p["rsi_entry"] <= rsi[i - 1]:
            e = c[i]
            pos = {"t": t[i], "entry": e, "target": e * (1 + p["tp"] / 100),
                   "stop": e * (1 - p["sl"] / 100), "bars": 0}
            out.append(("scalp", f"📝 PAPER ENTRY {p['symbol']} at {fmt(e)} (1m RSI {rsi[i]:.0f})\n"
                                 f"target {fmt(pos['target'])} | stop {fmt(pos['stop'])} | "
                                 f"exit in {p['hold']} min\nPaper trade for the test. Not a buy call."))
    # an open trade whose candles fell out of the window (long outage): close it at the last price
    if pos and pos["t"] < t[0]:
        net = (c[-1] / pos["entry"] - 1) * 100 - p["fee"]
        _log_trade(cur, "scalp_1m", p["symbol"], pos, t[-1], c[-1], "gap", net)
        pos = None
    _put(cur, "scalp", {"last_bar": t[-1], "open": pos})


# ── swing_4h ─────────────────────────────────────
def _run_swing(cur, out, force=False):
    p = SWING
    st = _get(cur, "swing", {"last_bar": {}, "open": {}})
    now = int(time.time() * 1000)
    # A new 4h candle closes every 4h; skip the 22 requests until one has.
    if not force and now < st.get("next_check", 0):
        return
    for sym in p["symbols"]:
        try:
            ks = closed_klines(sym, "4h", 500)
        except requests.RequestException as e:
            print(f"[watch] swing {sym} fetch failed: {e}")
            continue
        if len(ks) < p["ema"] + 20: continue
        t = [k[0] for k in ks]; lo = [k[2] for k in ks]; c = [k[3] for k in ks]
        rsi = rsi_series(c); ema = ema_series(c, p["ema"])
        last = st["last_bar"].get(sym)
        if last is None:
            st["last_bar"][sym] = t[-1]; continue
        for i in range(p["ema"], len(ks)):
            if t[i] <= last: continue
            pos = st["open"].get(sym)
            if pos:
                px = reason = None
                if lo[i] <= pos["stop"]:       px, reason = pos["stop"], "stop"
                elif rsi[i] < p["rsi_exit"]:   px, reason = c[i], "rsi<30"
                if px is not None:
                    ret = (px / pos["entry"] - 1) * 100 - p["fee"]
                    r = ret / pos["risk_pct"]
                    _log_trade(cur, "swing_4h", sym, pos, t[i], px, reason, ret, r)
                    del st["open"][sym]
                    out.append(("swing", f"📒 4H PAPER EXIT {sym} ({reason})\n{fmt(pos['entry'])} → "
                                         f"{fmt(px)} = {ret:+.2f}% ({r:+.2f}R)"))
            elif rsi[i] > p["rsi_entry"] >= rsi[i - 1] and c[i] > ema[i]:
                stop = min(lo[i - p["stop_lookback"]:i + 1])
                risk = (c[i] - stop) / c[i] * 100
                if 0 < risk <= p["max_risk"]:
                    st["open"][sym] = {"t": t[i], "entry": c[i], "stop": stop, "risk_pct": risk}
                    out.append(("swing",
                        f"📒 4H PAPER ENTRY {sym} (long)\nentry {fmt(c[i])} | stop {fmt(stop)} "
                        f"(−{risk:.1f}%)\nexit: stop, or 4h RSI below 30. No target.\n"
                        f"Risking $10 → ${10 / risk * 100:,.0f} position.\n"
                        f"Paper test, unproven rule. Not a buy call."))
        st["last_bar"][sym] = t[-1]
    # next candle closes at (last open + 4h) + 4h; check shortly after it
    newest = max(st["last_bar"].values()) if st["last_bar"] else now
    st["next_check"] = newest + 2 * FOUR_H_MS + 30_000
    _put(cur, "swing", st)


# ── entry point for /api/watch ───────────────────
def run(force_swing=False):
    out = []
    conn = db.get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK_ID,))
                if not cur.fetchone()[0]:
                    return {"skipped": "another run in progress"}
                alerts = _get(cur, "alerts", DEFAULT_ALERTS)
                errors = []
                for name, fn in (("scalp", lambda: _run_scalp(cur, out)),
                                 ("swing", lambda: _run_swing(cur, out, force_swing))):
                    try:
                        fn()
                    except Exception as e:     # one rule failing must not block the other
                        errors.append(f"{name}: {e}")
                        print(f"[watch] {name} failed: {e}")
    finally:
        conn.close()
    # send only after the state is committed, so a failed commit can't double-alert
    sent = 0
    for kind, text in out:
        if alerts.get(kind, True):
            for chat in config.ADMIN_CHAT_IDS:
                sent += bool(telegram.send_message(chat, html.escape(text)))
    return {"events": len(out), "sent": sent, "errors": errors}


# ── Telegram commands ────────────────────────────
def alerts_command(args: str) -> str:
    words = args.lower().split()
    conn = db.get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                a = dict(DEFAULT_ALERTS, **_get(cur, "alerts", DEFAULT_ALERTS))
                if words and words[-1] in ("on", "off"):
                    val = words[-1] == "on"
                    targets = [w for w in words[:-1] if w in a] or list(a)
                    for k in targets: a[k] = val
                    _put(cur, "alerts", a)
    finally:
        conn.close()
    icon = lambda v: "🔔 on" if v else "🔕 off"
    return ("<b>Paper alerts</b>\n"
            f"1m scalp (ETH): {icon(a['scalp'])}\n"
            f"4h swing (22 coins): {icon(a['swing'])}\n\n"
            "Muted rules keep paper-trading; you just don't get pinged.\n"
            "/alerts off · /alerts on · /alerts scalp off · /alerts swing on · /paper for results")


def paper_command() -> str:
    conn = db.get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT strategy, count(*) n, count(*) FILTER (WHERE ret_pct > 0) wins, "
                "avg(ret_pct) avg_ret, sum(ret_pct) sum_ret, sum(r) sum_r, avg(r) avg_r "
                "FROM paper_trades GROUP BY strategy")
            rows = {r["strategy"]: r for r in cur.fetchall()}
            cur.execute("SELECT value FROM paper_watch_state WHERE key = 'swing'")
            sw = cur.fetchone()
    finally:
        conn.close()
    lines = ["📊 <b>Paper results</b>\n"]
    s = rows.get("scalp_1m")
    if s:
        lines.append(f"<b>1m scalp</b>: {s['n']} trades, {s['wins']} wins after fees "
                     f"({s['wins'] / s['n'] * 100:.0f}%)\navg {float(s['avg_ret']):+.3f}%/trade · "
                     f"on $100/trade: ${float(s['sum_ret']):+.2f}\n")
    else:
        lines.append("<b>1m scalp</b>: no trades yet\n")
    w = rows.get("swing_4h")
    open_n = len((sw or [{}])[0].get("open", {})) if sw else 0
    if w:
        lines.append(f"<b>4h swing</b>: {w['n']} closed, {w['wins']} wins, total {float(w['sum_r']):+.1f}R "
                     f"(avg {float(w['avg_r']):+.2f}R) · risking $10/trade: ${float(w['sum_r']) * 10:+.0f}")
    else:
        lines.append("<b>4h swing</b>: no closed trades yet")
    lines.append(f"Open 4h positions: {open_n}")
    return "\n".join(lines)
