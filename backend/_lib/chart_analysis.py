#!/usr/bin/env python3
"""
chart_analysis.py — Technical analysis engine for trade confirmation.

Ported from the original BINANCE/chart_analysis.py bot. Confirms a funding
signal only when every check passes — funding worth holding for, price not
fighting its 4h move or the 15m EMA21, a reward:risk floor, and the risk
gate's vetoes (Binance flags, a 7/30-day collapse, red-flag news) — and
returns entry/TP/SL. RSI, EMA 9/21, MACD, Bollinger Bands, volume trend and
support/resistance are still computed and shown for context.
"""

import html
import time
from datetime import datetime, timedelta, timezone

import requests

from . import config

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "KTRADESSignals/1.0"})


# ═══════════════════════════════════════════════════
#  KLINE FETCHING
# ═══════════════════════════════════════════════════

def fetch_klines(symbol: str, interval: str, limit: int = 100) -> list:
    """Fetch candlestick data from Binance."""
    try:
        r = SESSION.get(f"{config.BASE_URL}/fapi/v1/klines", params={
            "symbol": symbol, "interval": interval, "limit": limit
        }, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        candles = []
        for k in data:
            candles.append({
                "time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })
        return candles
    except Exception:
        return []


# ═══════════════════════════════════════════════════
#  INDICATORS
# ═══════════════════════════════════════════════════

def calc_ema(closes: list, period: int) -> list:
    """Exponential Moving Average."""
    if len(closes) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = [sum(closes[:period]) / period]
    for price in closes[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def calc_rsi(closes: list, period: int = 14) -> float:
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return 50.0

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(closes: list) -> dict:
    """MACD: 12/26/9."""
    if len(closes) < 26:
        return {"macd": 0, "signal": 0, "histogram": 0, "crossover": None}

    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)

    diff = len(ema12) - len(ema26)
    ema12 = ema12[diff:]

    macd_line = [a - b for a, b in zip(ema12, ema26)]

    if len(macd_line) < 9:
        return {"macd": macd_line[-1] if macd_line else 0, "signal": 0, "histogram": 0, "crossover": None}

    signal_line = calc_ema(macd_line, 9)

    diff2 = len(macd_line) - len(signal_line)
    macd_trimmed = macd_line[diff2:]

    histogram = [m - s for m, s in zip(macd_trimmed, signal_line)]

    crossover = None
    if len(histogram) >= 3:
        if histogram[-1] > 0 and histogram[-2] <= 0:
            crossover = "BULLISH"
        elif histogram[-1] < 0 and histogram[-2] >= 0:
            crossover = "BEARISH"

    return {
        "macd": macd_trimmed[-1],
        "signal": signal_line[-1],
        "histogram": histogram[-1],
        "crossover": crossover,
    }


def calc_bollinger(closes: list, period: int = 20, std_dev: float = 2.0) -> dict:
    """Bollinger Bands."""
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "position": 0.5}

    recent = closes[-period:]
    middle = sum(recent) / period
    variance = sum((x - middle) ** 2 for x in recent) / period
    std = variance ** 0.5

    upper = middle + std_dev * std
    lower = middle - std_dev * std

    current = closes[-1]
    band_width = upper - lower
    position = (current - lower) / band_width if band_width > 0 else 0.5

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "position": round(position, 3),
    }


def calc_atr(candles: list, period: int = 14) -> float:
    """Average True Range."""
    if len(candles) < period + 1:
        return 0

    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0

    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period

    return atr


def calc_avg_range_pct(candles: list) -> float:
    """Average candle range, (high - low) / close in % — the same measure
    scanner.fetch_volatility filters on."""
    ranges = [(c["high"] - c["low"]) / c["close"] * 100 for c in candles if c["close"] > 0]
    return sum(ranges) / len(ranges) if ranges else 0.0


def find_support_resistance(candles: list, lookback: int = 30) -> dict:
    """Find support and resistance from recent swing highs/lows."""
    if len(candles) < 5:
        return {"support": 0, "resistance": 0}

    recent = candles[-lookback:] if len(candles) >= lookback else candles

    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    current = candles[-1]["close"]

    swing_highs = []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and \
           highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
            swing_highs.append(highs[i])

    swing_lows = []
    for i in range(2, len(lows) - 2):
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and \
           lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
            swing_lows.append(lows[i])

    resistances = [h for h in swing_highs if h > current]
    resistance = min(resistances) if resistances else max(highs)

    supports = [l for l in swing_lows if l < current]
    support = max(supports) if supports else min(lows)

    return {
        "support": support,
        "resistance": resistance,
    }


def calc_volume_trend(candles: list, lookback: int = 10) -> str:
    """Check if volume is increasing or decreasing."""
    if len(candles) < lookback:
        return "NEUTRAL"

    recent_vol = sum(c["volume"] for c in candles[-lookback // 2:]) / (lookback // 2)
    older_vol = sum(c["volume"] for c in candles[-lookback:-lookback // 2]) / (lookback // 2)

    if recent_vol > older_vol * 1.3:
        return "INCREASING"
    elif recent_vol < older_vol * 0.7:
        return "DECREASING"
    return "NEUTRAL"


# ═══════════════════════════════════════════════════
#  TRADE CONFIRMATION
# ═══════════════════════════════════════════════════

def analyze_chart(symbol: str, direction: str, funding_rate: float,
                  expected_funding_pct: float = None, extra_checks: list = None) -> dict:
    """
    Trade confirmation (strategy 5). Confirmed only if every check passes.

    funding_rate is the hourly-equivalent rate as a fraction (-0.0015 is
    -0.15%/h); expected_funding_pct is the scanner's estimate of what the
    planned hold collects, in %. This function's own checks:
      - funding worth holding for: at least MIN_CONFIRM_FUNDING_HOURLY_PCT
        per hour, or MIN_CONFIRM_EXPECTED_FUNDING_PCT over the hold
      - not fighting the move: for a long, the live price no lower than the
        5m close 4h before the latest one and at or above the closed 15m
        EMA21; for a short, the mirror image
      - reward:risk of at least MIN_RR_RATIO
    extra_checks are (passed, text) pairs from risk_checks (Binance flags,
    the 7/30-day move, news) and count exactly like these.

    Every check is reported passed or failed, so a rejected setup can't read
    as an approved one: v4 posted "NOT CONFIRMED (4/4 checks passed)" with
    four green ticks on BLUR, because the reward:risk floor that stopped it
    wasn't one of the listed checks.

    The 1h volatility cap isn't repeated: the scanner drops every coin at or
    above MAX_VOLATILITY before it gets here. It's still shown for context.

    Returns confirmed (bool), entry/tp/sl, the checks (details, failed), and
    indicator readings.
    """
    extra_checks = list(extra_checks or [])
    full_symbol = symbol + "USDT" if "USDT" not in symbol else symbol

    # One extra candle each: the last kline is still forming and is dropped below.
    candles_5m = fetch_klines(full_symbol, "5m", 101)
    time.sleep(0.1)
    candles_15m = fetch_klines(full_symbol, "15m", 61)
    time.sleep(0.1)
    candles_1h = fetch_klines(full_symbol, "1h", config.VOLATILITY_PERIOD_1H + 1)

    # 49 closed 5m candles for the 4h check, 21 closed 15m candles for the EMA.
    if len(candles_5m) < 50 or len(candles_15m) < 22:
        failed = ["Not enough candle data to analyze"] + [text for ok, text in extra_checks if not ok]
        return {"confirmed": False, "confidence": 0, "confirmations": sum(1 for ok, _ in extra_checks if ok),
                "max_confirmations": 4 + len(extra_checks), "details": ["❌ " + t for t in failed],
                "failed": failed, "reason": "Insufficient candle data"}

    # The forming candle's close is the live price: it is the entry, and the
    # trend checks compare it with closed candles. Every indicator itself is
    # computed on closed candles, so none of them repaints mid-candle.
    current_price = candles_5m[-1]["close"]
    candles_5m = candles_5m[:-1]
    candles_15m = candles_15m[:-1]
    candles_1h = candles_1h[:-1]

    closes_5m = [c["close"] for c in candles_5m]
    closes_15m = [c["close"] for c in candles_15m]

    # Context only — none of these vote.
    rsi_5m = calc_rsi(closes_5m, 14)
    rsi_15m = calc_rsi(closes_15m, 14)
    ema9 = calc_ema(closes_5m, 9)
    ema21 = calc_ema(closes_5m, 21)
    ema_bullish = ema9[-1] > ema21[-1] if ema9 and ema21 else False
    macd_5m = calc_macd(closes_5m)
    bb = calc_bollinger(closes_15m, 20, 2.0)
    atr_5m = calc_atr(candles_5m, 14)
    atr_15m = calc_atr(candles_15m, 14)
    sr = find_support_resistance(candles_15m, 30)
    vol_trend = calc_volume_trend(candles_5m, 10)
    vol_1h = calc_avg_range_pct(candles_1h) if len(candles_1h) >= 2 else None

    atr = atr_5m if atr_5m > 0 else atr_15m
    if atr == 0:
        atr = current_price * 0.005

    # Stops are ATR-only. Capping them at nearby support/resistance could only
    # ever pull them closer to entry — as close as 0.29% on posted trades,
    # inside a single candle's noise for these coins. The target is capped at
    # the nearest resistance/support, which is what the reward:risk check
    # below guards: a long right under resistance has little room to run.
    entry = current_price
    if direction == "LONG":
        sl = entry - (atr * 1.5)
        risk = entry - sl
        tp_rr = entry + (risk * 2.0)
        tp_resistance = sr["resistance"] * 0.998
        tp = min(tp_rr, tp_resistance) if tp_resistance > entry else tp_rr
        if tp <= entry:
            tp = entry + (atr * 2.0)
    else:  # SHORT
        sl = entry + (atr * 1.5)
        risk = sl - entry
        tp_rr = entry - (risk * 2.0)
        tp_support = sr["support"] * 1.002
        tp = max(tp_rr, tp_support) if tp_support < entry else tp_rr
        if tp >= entry:
            tp = entry - (atr * 2.0)

    risk_amount = abs(entry - sl)
    reward_amount = abs(tp - entry)
    rr_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
    risk_pct = (risk_amount / entry * 100) if entry > 0 else 0

    # The checklist.
    long = direction == "LONG"
    hourly_pct = abs(funding_rate) * 100
    ema21_15m = calc_ema(closes_15m, 21)
    ema21_15m = ema21_15m[-1] if ema21_15m else None
    # Live price vs the 5m close 48 candles before the latest closed one:
    # 4h to 4h05m ago, depending on how far into the current candle we are.
    change_4h = (current_price / closes_5m[-49] - 1) * 100
    vs_ema_pct = (current_price / ema21_15m - 1) * 100 if ema21_15m else None
    side_rule = "long needs ≥ 0" if long else "short needs ≤ 0"

    expected_txt = f", ~{expected_funding_pct:.2f}% over the hold" if expected_funding_pct is not None else ""
    checks = [
        (hourly_pct >= config.MIN_CONFIRM_FUNDING_HOURLY_PCT
         or (expected_funding_pct or 0) >= config.MIN_CONFIRM_EXPECTED_FUNDING_PCT,
         f"Funding {hourly_pct:.3f}%/h{expected_txt} (needs ≥ {config.MIN_CONFIRM_FUNDING_HOURLY_PCT}%/h "
         f"or ≥ {config.MIN_CONFIRM_EXPECTED_FUNDING_PCT}% total)"),
        ((change_4h >= 0) if long else (change_4h <= 0),
         f"4h change {change_4h:+.2f}% ({side_rule})"),
        (vs_ema_pct is not None and ((vs_ema_pct >= 0) if long else (vs_ema_pct <= 0)),
         f"Price vs 15m EMA21 {vs_ema_pct:+.2f}% ({side_rule})" if vs_ema_pct is not None
         else "15m EMA21 unavailable"),
        (rr_ratio >= config.MIN_RR_RATIO,
         f"Reward:risk 1:{rr_ratio:.2f} (needs at least 1:{config.MIN_RR_RATIO})"),
    ] + extra_checks
    passed = sum(1 for ok, _ in checks if ok)
    details = [("✅ " if ok else "❌ ") + text for ok, text in checks]
    failed = [text for ok, text in checks if not ok]
    confirmed = not failed
    # Share of checks passed, kept under the old key for the track record.
    # It is not a win probability.
    confidence = int(passed / len(checks) * 100)

    return {
        "confirmed": confirmed,
        "confidence": confidence,
        "direction": direction,
        "entry": entry,
        "tp": tp,
        "sl": sl,
        "rr_ratio": round(rr_ratio, 2),
        "risk_pct": round(risk_pct, 2),
        "confirmations": passed,
        "max_confirmations": len(checks),
        "details": details,
        "failed": failed,
        "indicators": {
            "rsi_5m": round(rsi_5m, 1),
            "rsi_15m": round(rsi_15m, 1),
            "ema_bullish": ema_bullish,
            "macd_histogram": round(macd_5m["histogram"], 6),
            "macd_crossover": macd_5m["crossover"],
            "bb_position": bb["position"],
            "atr": round(atr, 6),
            "volume_trend": vol_trend,
            "support": round(sr["support"], 6),
            "resistance": round(sr["resistance"], 6),
            "change_4h": round(change_4h, 2),
            "ema21_15m": round(ema21_15m, 8) if ema21_15m is not None else None,
            "vol_1h": round(vol_1h, 2) if vol_1h is not None else None,
        },
        "reason": "All checks passed" if confirmed else f"{len(failed)} of {len(checks)} checks failed",
    }


# ═══════════════════════════════════════════════════
#  TELEGRAM FORMATTING
# ═══════════════════════════════════════════════════

def _utc(ts: datetime) -> str:
    return ts.strftime("%d %b %H:%M UTC")


def format_analysis_telegram(symbol: str, analysis: dict, signal: dict,
                             now: datetime = None, close_by: datetime = None) -> str:
    """Telegram card for one analyzed coin. Only a confirmed coin gets a
    trade card; anything else is a NO TRADE card that lists just the checks
    it failed. Check texts can carry news headlines, so they're escaped.

    now and close_by are the logged row's created_at and resolve_at, so the
    card's entry window and exit deadline match what the track record scores;
    without them, now and now + the scanner's hold."""
    total = analysis["max_confirmations"]
    if not analysis["confirmed"]:
        failed = analysis.get("failed") or [analysis.get("reason", "Analysis failed")]
        return (
            f"⛔ <b>NO TRADE — {symbol}</b>\n"
            + "\n".join(f"  ❌ {html.escape(t, quote=False)}" for t in failed)
            + f"\n<i>{analysis['confirmations']} of {total} checks passed; a trade needs all {total}. "
            f"Don't trade this coin.</i>"
        )

    direction_emoji = "🟢 LONG" if analysis["direction"] == "LONG" else "🔴 SHORT"
    ind = analysis["indicators"]

    entry = analysis["entry"]
    if entry > 100:
        fmt = ",.2f"
    elif entry > 1:
        fmt = ",.4f"
    else:
        fmt = ",.6f"

    # One exit rule, the one the track record scores: TP, SL, or the end of
    # the scanner's hold, whichever comes first.
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    close_by = (close_by or now + timedelta(minutes=signal["hold_min"])).astimezone(timezone.utc)
    hold = round((close_by - now).total_seconds() / 60)
    enter_by = now + timedelta(minutes=config.ENTRY_VALID_MIN)
    risk_pct = analysis["risk_pct"]
    sizing = (
        f"📏 <b>Size:</b>   the stop is {risk_pct}% away, so risking 1% of your account means a position "
        f"of at most {100 / risk_pct:.0f}% of it\n" if risk_pct > 0 else ""
    )
    payments = signal["payments_catchable"]

    return (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>TRADE SIGNAL: {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📍 Direction: <b>{direction_emoji}</b>\n"
        f"🔑 Checks: <b>all {total} passed</b>\n\n"
        f"💵 <b>Entry:</b>  ${entry:{fmt}} — enter by {enter_by.strftime('%H:%M UTC')} or skip it\n"
        f"🎯 <b>TP:</b>     ${analysis['tp']:{fmt}}\n"
        f"🛑 <b>SL:</b>     ${analysis['sl']:{fmt}}\n"
        f"📊 <b>R:R:</b>    1:{analysis['rr_ratio']}\n"
        f"⏱ <b>Exit:</b>   at TP, at SL, or at {_utc(close_by)} (~{hold}min), whichever comes first\n"
        f"{sizing}\n"
        f"💰 Funding: {signal['funding_rate_raw']:.4f}%/{signal['funding_interval_h']}h "
        f"(${signal['funding_earn']:.4f} per $100, {signal['funding_rate']:.4f}%/hr equiv.)"
        f"{'' if signal['funding_catchable'] else ' ⚠️ may pay out after the exit'}\n"
        f"🔁 Persistent ({signal['persistence_ratio']*100:.0f}% of recent payments) — the hold collects "
        f"{payments} payout{'s' if payments != 1 else ''} (~${signal['est_total_funding_earn']:.4f} per $100)\n\n"
        f"✅ <b>Checks:</b>\n"
        + "\n".join(f"  {html.escape(d, quote=False)}" for d in analysis["details"]) +
        f"\n\n"
        f"📊 <b>Indicators</b> (context, not scored):\n"
        f"  RSI: 5m={ind['rsi_5m']} | 15m={ind['rsi_15m']}\n"
        f"  EMA 9/21 (5m): {'Bullish' if ind['ema_bullish'] else 'Bearish'}\n"
        f"  MACD: {ind['macd_crossover'] or 'No cross'} (hist: {ind['macd_histogram']:.6f})\n"
        f"  BB Position: {ind['bb_position']}\n"
        f"  1h volatility: {ind['vol_1h']}%\n"
        f"  Volume: {ind['volume_trend']}\n"
        f"  Support: ${ind['support']:{fmt}}\n"
        f"  Resistance: ${ind['resistance']:{fmt}}\n\n"
        f"<i>⚠️ One short trade, not a long-term hold. Every result is posted, losses included: "
        f"{config.SITE_URL}/history</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
