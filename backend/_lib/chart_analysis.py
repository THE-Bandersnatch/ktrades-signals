#!/usr/bin/env python3
"""
chart_analysis.py — Technical analysis engine for trade confirmation.

Ported from the original BINANCE/chart_analysis.py bot. Confirms a funding
signal with the trend-aligned checklist — funding worth holding for, calm
1h candles, price not fighting its 4h move or the 15m EMA21 — and returns
entry/TP/SL/hold time. RSI, EMA 9/21, MACD, Bollinger Bands, volume trend
and support/resistance are still computed and shown for context.
"""

import time
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
                  expected_funding_pct: float = None) -> dict:
    """
    Trade confirmation with the trend-aligned checklist (strategy 4).

    funding_rate is the hourly-equivalent rate as a fraction (-0.0015 is
    -0.15%/h); expected_funding_pct is the scanner's estimate of what the
    planned hold collects, in %. Confirmed only if every check passes:
      - funding worth holding for: at least MIN_CONFIRM_FUNDING_HOURLY_PCT
        per hour, or MIN_CONFIRM_EXPECTED_FUNDING_PCT over the hold
      - 1h volatility under MAX_VOLATILITY
      - not fighting the move: a long needs price no lower than 4h ago and
        at or above the 15m EMA21; a short, the mirror image
    and then only with a reward:risk of at least MIN_RR_RATIO.

    It replaced a score that rewarded RSI < 40 and a lower-Bollinger touch,
    which kept approving coins in the middle of a dump. RSI, EMA 9/21, MACD,
    the bands and volume are still reported but no longer vote.

    Returns confirmed (bool), entry/tp/sl, hold_time, the checks and their
    details, and indicator readings.
    """

    full_symbol = symbol + "USDT" if "USDT" not in symbol else symbol

    # One extra candle each: the last kline is still forming and is dropped below.
    candles_5m = fetch_klines(full_symbol, "5m", 101)
    time.sleep(0.1)
    candles_15m = fetch_klines(full_symbol, "15m", 61)
    time.sleep(0.1)
    candles_1h = fetch_klines(full_symbol, "1h", config.VOLATILITY_PERIOD_1H + 1)

    if len(candles_5m) < 2 or len(candles_15m) < 2:
        # Same keys a rejected analysis carries — format_analysis_telegram reads
        # them, and a KeyError there used to abort the scan.
        return {"confirmed": False, "confidence": 0, "confirmations": 0, "max_confirmations": 4,
                "details": [], "reason": "Insufficient candle data"}

    # The forming candle's close is the live price, used as the entry. Indicators
    # computed on it repaint tick by tick, so everything below uses closed candles.
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

    # The checklist.
    long = direction == "LONG"
    hourly_pct = abs(funding_rate) * 100
    ema21_15m = calc_ema(closes_15m, 21)
    ema21_15m = ema21_15m[-1] if ema21_15m else None
    # The closed 5m candle 48 before the latest closed one closed 4h before it.
    change_4h = (current_price / closes_5m[-49] - 1) * 100 if len(closes_5m) >= 49 else None
    vs_ema_pct = (current_price / ema21_15m - 1) * 100 if ema21_15m else None
    vol_1h = calc_avg_range_pct(candles_1h) if len(candles_1h) >= 2 else None
    side_rule = "long needs ≥ 0" if long else "short needs ≤ 0"

    expected_txt = f", ~{expected_funding_pct:.2f}% over the hold" if expected_funding_pct is not None else ""
    checks = [
        (hourly_pct >= config.MIN_CONFIRM_FUNDING_HOURLY_PCT
         or (expected_funding_pct or 0) >= config.MIN_CONFIRM_EXPECTED_FUNDING_PCT,
         f"Funding {hourly_pct:.3f}%/h{expected_txt} (needs ≥ {config.MIN_CONFIRM_FUNDING_HOURLY_PCT}%/h "
         f"or ≥ {config.MIN_CONFIRM_EXPECTED_FUNDING_PCT}% total)"),
        (vol_1h is not None and vol_1h < config.MAX_VOLATILITY,
         f"1h volatility {vol_1h:.2f}% (needs under {config.MAX_VOLATILITY:.0f}%)" if vol_1h is not None
         else "1h volatility unavailable"),
        (change_4h is not None and ((change_4h >= 0) if long else (change_4h <= 0)),
         f"4h change {change_4h:+.2f}% ({side_rule})" if change_4h is not None
         else "4h change unavailable"),
        (vs_ema_pct is not None and ((vs_ema_pct >= 0) if long else (vs_ema_pct <= 0)),
         f"Price vs 15m EMA21 {vs_ema_pct:+.2f}% ({side_rule})" if vs_ema_pct is not None
         else "15m EMA21 unavailable"),
    ]
    passed = sum(1 for ok, _ in checks if ok)
    details = [("✅ " if ok else "❌ ") + text for ok, text in checks]
    confirmed = passed == len(checks)
    # Share of checks passed, kept under the old key for the track record.
    # It is not a win probability.
    confidence = int(passed / len(checks) * 100)

    atr = atr_5m if atr_5m > 0 else atr_15m
    if atr == 0:
        atr = current_price * 0.005

    # Stops are ATR-only. Capping them at nearby support/resistance could only
    # ever pull them closer to entry — as close as 0.29% on posted trades,
    # inside a single candle's noise for these coins.
    if direction == "LONG":
        entry = current_price

        sl = entry - (atr * 1.5)

        risk = entry - sl
        tp_rr = entry + (risk * 2.0)
        tp_resistance = sr["resistance"] * 0.998
        tp = min(tp_rr, tp_resistance) if tp_resistance > entry else tp_rr

        if tp <= entry:
            tp = entry + (atr * 2.0)

    else:  # SHORT
        entry = current_price

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

    reason = "All checks passed" if confirmed else f"{len(checks) - passed} of {len(checks)} checks failed"
    # The TP is still capped at the nearest resistance/support, so a setup can
    # end up targeting less than it risks — confirm only above the floor.
    if confirmed and rr_ratio < config.MIN_RR_RATIO:
        confirmed = False
        reason = f"R:R 1:{rr_ratio:.2f} is below the 1:{config.MIN_RR_RATIO} minimum"

    if atr > 0:
        bars_to_tp = reward_amount / atr
        hold_time = int(bars_to_tp * 5)
        hold_time = max(5, min(60, hold_time))
    else:
        hold_time = 15

    risk_pct = (risk_amount / entry * 100) if entry > 0 else 0

    return {
        "confirmed": confirmed,
        "confidence": confidence,
        "direction": direction,
        "entry": entry,
        "tp": tp,
        "sl": sl,
        "rr_ratio": round(rr_ratio, 2),
        "hold_time": hold_time,
        "risk_pct": round(risk_pct, 2),
        "confirmations": passed,
        "max_confirmations": len(checks),
        "details": details,
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
            "change_4h": round(change_4h, 2) if change_4h is not None else None,
            "ema21_15m": round(ema21_15m, 8) if ema21_15m is not None else None,
            "vol_1h": round(vol_1h, 2) if vol_1h is not None else None,
        },
        "reason": reason,
    }


# ═══════════════════════════════════════════════════
#  TELEGRAM FORMATTING
# ═══════════════════════════════════════════════════

def format_analysis_telegram(symbol: str, analysis: dict, signal: dict) -> str:
    """Format analysis result for Telegram message."""

    if not analysis["confirmed"]:
        return (
            f"🔍 <b>{symbol}</b> — Analysis\n"
            f"❌ <b>NOT CONFIRMED</b> ({analysis['confirmations']}/{analysis['max_confirmations']} checks passed)\n"
            f"Reason: {analysis['reason']}\n\n"
            + "\n".join(f"  {d}" for d in analysis["details"])
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

    return (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>TRADE SIGNAL: {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📍 Direction: <b>{direction_emoji}</b>\n"
        f"🔑 Checks: <b>{analysis['confirmations']}/{analysis['max_confirmations']} passed</b> "
        f"(trend-aligned setup)\n\n"
        f"💵 <b>Entry:</b>  ${entry:{fmt}}\n"
        f"🎯 <b>TP:</b>     ${analysis['tp']:{fmt}}\n"
        f"🛑 <b>SL:</b>     ${analysis['sl']:{fmt}}\n"
        f"📊 <b>R:R:</b>    1:{analysis['rr_ratio']}\n"
        f"⏱ <b>Hold:</b>   ~{analysis['hold_time']}min\n"
        f"⚠️ <b>Risk:</b>   {analysis['risk_pct']}% of entry\n\n"
        f"💰 Funding: {signal['funding_rate_raw']:.4f}%/{signal['funding_interval_h']}h "
        f"(${signal['funding_earn']:.4f} per $100, {signal['funding_rate']:.4f}%/hr equiv.)"
        f"{'' if signal['funding_catchable'] else ' ⚠️ may pay out after hold window'}\n"
        f"🔁 Persistent ({signal['persistence_ratio']*100:.0f}% of recent payments) — "
        f"funding plan wants ~{signal['hold_min']}min for {signal['payments_catchable']}x payout"
        f"{'s' if signal['payments_catchable'] != 1 else ''} "
        f"(~${signal['est_total_funding_earn']:.4f} total per $100)"
        + (
            f"\n⚖️ Note: technical TP (~{analysis['hold_time']}min) comes well before the funding "
            f"plan (~{signal['hold_min']}min) — decide whether to exit at TP or hold for the extra payouts"
            if signal["hold_min"] - analysis["hold_time"] >= 15 else ""
        )
        + "\n\n"
        f"✅ <b>Entry checks:</b>\n"
        + "\n".join(f"  {d}" for d in analysis["details"]) +
        f"\n\n"
        f"📊 <b>Indicators</b> (context, not scored):\n"
        f"  RSI: 5m={ind['rsi_5m']} | 15m={ind['rsi_15m']}\n"
        f"  EMA 9/21 (5m): {'Bullish' if ind['ema_bullish'] else 'Bearish'}\n"
        f"  MACD: {ind['macd_crossover'] or 'No cross'} (hist: {ind['macd_histogram']:.6f})\n"
        f"  BB Position: {ind['bb_position']}\n"
        f"  Volume: {ind['volume_trend']}\n"
        f"  Support: ${ind['support']:{fmt}}\n"
        f"  Resistance: ${ind['resistance']:{fmt}}\n\n"
        f"<i>⏳ Signal valid for next {analysis['hold_time']}min</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
