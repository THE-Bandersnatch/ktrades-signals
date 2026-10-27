#!/usr/bin/env python3
"""
scanner.py — Binance 1H Funding Rate Signal Engine

Ported from the original BINANCE/scanner.py bot. No API key
required — uses public Binance Futures endpoints only.
"""
import time
from typing import Optional, Union

import requests

from . import config

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "KTRADESSignals/1.0"})


# ═══════════════════════════════════════════════════
#  DATA FETCHING
# ═══════════════════════════════════════════════════

def api_get(endpoint: str, params: dict = None) -> Optional[Union[dict, list]]:
    """Safe GET request to Binance API with rate limit handling.

    Failures print to stdout (visible in `vercel logs`) instead of just
    vanishing into a None — a silent failure here looks identical to a
    legitimate empty result to every caller upstream, which previously made
    "Binance blocked/timed out" indistinguishable from "market has nothing
    right now."
    """
    try:
        url = f"{config.BASE_URL}{endpoint}"
        r = SESSION.get(url, params=params, timeout=10)
        if r.status_code == 429:
            print(f"[Binance API] 429 rate limited on {endpoint}")
            time.sleep(30)
            return None
        if r.status_code != 200:
            print(f"[Binance API] {r.status_code} on {endpoint}: {r.text[:200]}")
            return None
        return r.json()
    except Exception as e:
        print(f"[Binance API] {type(e).__name__} on {endpoint}: {e}")
        return None


def fetch_funding_intervals() -> tuple:
    """Get funding-interval overrides currently in effect.

    Binance's /fundingInfo only lists symbols whose interval deviates from
    the exchange default — everything absent from it sits at
    config.DEFAULT_FUNDING_INTERVAL_H. Returns (overrides: {symbol: hours}, ok).
    ok is False only when the API call itself failed (network error,
    non-200, rate limit).
    """
    data = api_get("/fapi/v1/fundingInfo")
    if data is None:
        return {}, False

    overrides = {}
    for item in data:
        overrides[item["symbol"]] = item.get("fundingIntervalHours", config.DEFAULT_FUNDING_INTERVAL_H)
    return overrides, True


def fetch_all_funding_rates() -> tuple:
    """Get current funding rates + mark prices for every USDT-margined perp.

    Unlike the old 1h-only design, this is the primary source of the scan
    universe — every symbol Binance quotes a funding rate for, regardless of
    interval. Returns (rates: {symbol: {...}}, ok).
    """
    data = api_get("/fapi/v1/premiumIndex")
    if data is None:
        return {}, False

    rates = {}
    for item in data:
        sym = item["symbol"]
        if not sym.endswith("USDT"):
            continue
        rates[sym] = {
            "funding_rate": float(item.get("lastFundingRate", 0)),
            "mark_price": float(item.get("markPrice", 0)),
            "next_funding_time": int(item.get("nextFundingTime", 0)),
            "index_price": float(item.get("indexPrice", 0)),
        }
    return rates, True


def fetch_market_data(symbols: list) -> dict:
    """Get 24h ticker data: volume, price change, high/low."""
    data = api_get("/fapi/v1/ticker/24hr")
    if not data:
        return {}

    market = {}
    symbol_set = set(symbols)
    for item in data:
        sym = item["symbol"]
        if sym in symbol_set:
            volume = float(item.get("quoteVolume", 0))
            price_change_pct = float(item.get("priceChangePercent", 0))
            high = float(item.get("highPrice", 0))
            low = float(item.get("lowPrice", 0))
            last = float(item.get("lastPrice", 1))

            market[sym] = {
                "volume_usdt": volume,
                "price_change_24h": price_change_pct,
                "high_24h": high,
                "low_24h": low,
                "last_price": last,
                "range_pct": ((high - low) / last * 100) if last > 0 else 0,
            }
    return market


def fetch_volatility(symbol: str) -> dict:
    """Calculate volatility from closed 15m and 1h klines.

    Binance's last kline is still forming, so including it made the same
    coin's reading depend on how far into the candle the scan ran — a scan at
    :01 saw an almost empty last hour. Fetch one extra and drop it.
    """
    result = {"vol_1h": 0, "vol_15m": 0, "combined": 0}

    klines_1h = (api_get("/fapi/v1/klines", {
        "symbol": symbol, "interval": "1h", "limit": config.VOLATILITY_PERIOD_1H + 1
    }) or [])[:-1]
    if len(klines_1h) >= 2:
        ranges = []
        for k in klines_1h:
            h, l, c = float(k[2]), float(k[3]), float(k[4])
            if c > 0:
                ranges.append((h - l) / c * 100)
        result["vol_1h"] = sum(ranges) / len(ranges) if ranges else 0

    klines_15m = (api_get("/fapi/v1/klines", {
        "symbol": symbol, "interval": "15m", "limit": config.VOLATILITY_PERIOD_15M + 1
    }) or [])[:-1]
    if len(klines_15m) >= 2:
        ranges = []
        for k in klines_15m:
            h, l, c = float(k[2]), float(k[3]), float(k[4])
            if c > 0:
                ranges.append((h - l) / c * 100)
        result["vol_15m"] = sum(ranges) / len(ranges) if ranges else 0

    result["combined"] = (result["vol_15m"] * 0.6 + result["vol_1h"] * 0.4)
    return result


def fetch_open_interest(symbol: str) -> float:
    """Get open interest quantity (converted to USDT by the caller)."""
    data = api_get("/fapi/v1/openInterest", {"symbol": symbol})
    if not data:
        return 0
    return float(data.get("openInterest", 0))


def fetch_funding_history(symbol: str, limit: int = None) -> list:
    """Get a symbol's actual recent funding payments (oldest first).

    Distinct from fetch_all_funding_rates(), which only has the current/
    predicted rate — this is what Binance actually paid out historically,
    used to tell a sustained crowded-positioning regime apart from a
    one-reading spike that may well revert before it can be collected.
    """
    limit = limit or config.PERSISTENCE_HISTORY_COUNT
    data = api_get("/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})
    if not data:
        return []
    return [
        {"funding_time": int(d["fundingTime"]), "funding_rate": float(d["fundingRate"])}
        for d in data
        if d.get("rateType", "Regular") == "Regular"
    ]


def fetch_liquidations(symbol: str) -> list:
    """Get recent forced liquidations for a symbol.

    Not called — /fapi/v1/forceOrders is a signed USER_DATA endpoint that only
    returns the caller's own liquidations, and without an API key it 401s.
    See the cascade note in generate_signals.
    """
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (config.CASCADE_WINDOW_MIN * 60 * 1000)

    data = api_get("/fapi/v1/forceOrders", {
        "symbol": symbol,
        "startTime": start_ms,
        "limit": 100,
    })
    if not data:
        return []

    liqs = []
    for order in data:
        liqs.append({
            "side": order.get("side", ""),
            "price": float(order.get("price", 0)),
            "qty": float(order.get("origQty", 0)),
            "time": int(order.get("time", 0)),
            "usdt_value": float(order.get("price", 0)) * float(order.get("origQty", 0)),
        })
    return liqs


def fetch_context_features(symbol: str) -> dict:
    """Market context at signal time, stored with each signal for later
    research. Binance only serves ~30 days of open-interest and long/short
    history, so anything not captured now can never be backtested. None of
    it feeds the signal decision yet — on 383 signals none of these split
    winners from losers once results were weighted per coin."""
    out = {}
    k = api_get("/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": 25})
    if k and len(k) >= 25:
        closes = [float(x[4]) for x in k]
        out["mom_4h_pct"] = round((closes[-1] / closes[-5] - 1) * 100, 3)
        out["mom_24h_pct"] = round((closes[-1] / closes[0] - 1) * 100, 3)
    oi = api_get("/futures/data/openInterestHist", {"symbol": symbol, "period": "1h", "limit": 5})
    if oi and len(oi) >= 5:
        first, last = float(oi[0]["sumOpenInterest"]), float(oi[-1]["sumOpenInterest"])
        if first > 0:
            out["oi_change_4h_pct"] = round((last / first - 1) * 100, 3)
    ls = api_get("/futures/data/globalLongShortAccountRatio", {"symbol": symbol, "period": "1h", "limit": 1})
    if ls:
        out["long_short_ratio"] = float(ls[-1]["longShortRatio"])
    return out


# ═══════════════════════════════════════════════════
#  ANALYSIS
# ═══════════════════════════════════════════════════

def detect_cascade(liquidations: list) -> dict:
    """Detect if there's a liquidation cascade (cluster of liqs in one direction)."""
    if len(liquidations) < config.CASCADE_MIN_COUNT:
        return {"detected": False, "direction": None, "count": 0, "total_usdt": 0}

    buy_liqs = [l for l in liquidations if l["side"] == "BUY"]
    sell_liqs = [l for l in liquidations if l["side"] == "SELL"]

    buy_total = sum(l["usdt_value"] for l in buy_liqs)
    sell_total = sum(l["usdt_value"] for l in sell_liqs)

    if len(sell_liqs) >= config.CASCADE_MIN_COUNT and sell_total >= config.CASCADE_MIN_USDT:
        return {
            "detected": True,
            "direction": "LONG_LIQUIDATED",
            "count": len(sell_liqs),
            "total_usdt": sell_total,
            "magnitude": sell_total,
        }
    elif len(buy_liqs) >= config.CASCADE_MIN_COUNT and buy_total >= config.CASCADE_MIN_USDT:
        return {
            "detected": True,
            "direction": "SHORT_LIQUIDATED",
            "count": len(buy_liqs),
            "total_usdt": buy_total,
            "magnitude": buy_total,
        }

    return {"detected": False, "direction": None, "count": len(liquidations), "total_usdt": buy_total + sell_total}


def analyze_persistence(current_rate: float, history: list) -> dict:
    """Check whether the current extreme rate is a sustained regime rather
    than a one-off spike, using the symbol's own actual recent payments.

    A single extreme print is often just noise — worth roughly one fee's
    width, not an edge. Requiring most of the recent history to agree in
    both direction and magnitude is what justifies planning to hold across
    multiple future payments instead of gambling on catching just this one.
    """
    if not history:
        return {"persistent": False, "ratio": 0.0, "magnitude_ratio": 0.0, "count": 0}

    same_dir = [h["funding_rate"] for h in history if (h["funding_rate"] > 0) == (current_rate > 0)]
    ratio = len(same_dir) / len(history)

    avg_same_dir_mag = sum(abs(r) for r in same_dir) / len(same_dir) if same_dir else 0.0
    magnitude_ratio = avg_same_dir_mag / abs(current_rate) if current_rate != 0 else 0.0

    persistent = (
        ratio >= config.PERSISTENCE_MIN_RATIO
        and magnitude_ratio >= config.PERSISTENCE_MIN_MAGNITUDE_RATIO
    )
    return {
        "persistent": persistent,
        "ratio": round(ratio, 2),
        "magnitude_ratio": round(magnitude_ratio, 2),
        "count": len(history),
    }


def estimate_multi_period_capture(interval_h: int, next_funding_time: int, now_ms: int) -> dict:
    """How many consecutive payments fit inside an extended, persistence-
    justified hold (config.PERSISTENCE_MAX_HOLD_MIN), and the hold time
    that implies.

    Shorter intervals fit more payments into the same time budget — this is
    the actual mechanism that makes a 1h-interval coin worth more than a
    single-print comparison would suggest, instead of a flat preference for
    the 1h bucket regardless of whether its crowding is sustained.
    """
    time_to_first_min = max(0, (next_funding_time - now_ms) / 60000)
    budget_min = config.PERSISTENCE_MAX_HOLD_MIN
    interval_min = interval_h * 60

    if time_to_first_min > budget_min:
        return {"payments_catchable": 0, "hold_min": 0}

    remaining = budget_min - time_to_first_min
    payments_catchable = 1 + int(remaining // interval_min)
    hold_min = int(min(budget_min, time_to_first_min + (payments_catchable - 1) * interval_min + 5))
    return {"payments_catchable": payments_catchable, "hold_min": hold_min}


def determine_direction(funding_rate: float, cascade: dict, price_change: float) -> str:
    """Determine trade direction based on funding + cascade + momentum."""
    if funding_rate > 0:
        direction = "SHORT"
    else:
        direction = "LONG"

    if cascade["detected"]:
        if cascade["direction"] == "LONG_LIQUIDATED":
            direction = "LONG"
        elif cascade["direction"] == "SHORT_LIQUIDATED":
            direction = "SHORT"

    return direction


def calculate_risk_score(volatility: float, funding_rate: float, volume: float,
                          cascade: dict, oi: float) -> int:
    """Risk score 0-100. Higher = more dangerous."""
    score = 0

    score += min(30, volatility * 10)

    abs_funding = abs(funding_rate) * 100
    score += min(25, abs_funding * 50)

    if volume < 10_000_000:
        score += 20
    elif volume < 50_000_000:
        score += 10
    elif volume < 100_000_000:
        score += 5

    if cascade["detected"]:
        score += 15

    if oi < config.MIN_OI_USDT:
        score += 10

    return min(100, int(score))


def calculate_hold_time(volatility: float, cascade: dict) -> int:
    """Suggest hold time in minutes based on conditions."""
    base = config.SUGGESTED_HOLD_MIN

    if cascade["detected"]:
        base = 10

    if volatility > 3:
        base = max(5, base - 5)
    elif volatility < 1:
        base = min(config.SUGGESTED_HOLD_MAX, base + 15)

    return base


# ═══════════════════════════════════════════════════
#  SIGNAL GENERATION
# ═══════════════════════════════════════════════════

def generate_signals() -> tuple:
    """Main signal generation pipeline.

    Scans every USDT-margined perpetual regardless of funding interval, and
    compares funding intensity on an hourly-equivalent basis — an 8h-interval
    coin at -0.40%/8h (-0.05%/hr equivalent) is judged the same way as a
    1h-interval coin at -0.05%/hr, instead of only ever looking at the small
    handful of symbols currently overridden to a 1h interval. A symbol only
    becomes a candidate if its next funding payment also falls within
    SUGGESTED_HOLD_MAX minutes — otherwise a scalp-length hold would close
    out before ever actually collecting it, so surfacing it as a "funding"
    signal would overstate what the trade can realistically capture.

    Returns (signals, meta). meta always carries api_ok / scanned_symbols /
    near_misses so callers can render an informative message even when
    signals comes back empty — see telegram.format_signals_message.
    """

    intervals, intervals_ok = fetch_funding_intervals()
    rates, rates_ok = fetch_all_funding_rates()
    api_ok = intervals_ok and rates_ok
    if not rates:
        return [], {"api_ok": api_ok, "scanned_symbols": 0, "near_misses": []}

    symbols = list(rates.keys())
    market = fetch_market_data(symbols)

    now_ms = int(time.time() * 1000)
    max_catchable_ms = config.SUGGESTED_HOLD_MAX * 60 * 1000

    enriched = {}
    for sym in symbols:
        if sym not in market:
            continue
        interval_h = intervals.get(sym, config.DEFAULT_FUNDING_INTERVAL_H)
        enriched[sym] = {
            "interval_h": interval_h,
            "hourly_rate": rates[sym]["funding_rate"] / interval_h,
        }

    near_misses = []
    for sym, e in enriched.items():
        near_misses.append({
            "symbol": sym.replace("USDT", ""),
            "funding_rate_pct": e["hourly_rate"] * 100,
            "volume_m": round(market[sym]["volume_usdt"] / 1_000_000, 1),
            "passes_volume": market[sym]["volume_usdt"] >= config.MIN_VOLUME_USDT,
        })
    near_misses.sort(key=lambda x: -abs(x["funding_rate_pct"]))
    # The radar is what the public page shows between trades: the most
    # crowded liquid coins right now, whether or not they became signals.
    radar = [
        {
            "symbol": nm["symbol"],
            "funding_rate_pct": round(nm["funding_rate_pct"], 4),
            "volume_m": nm["volume_m"],
            "next_funding": rates[nm["symbol"] + "USDT"]["next_funding_time"],
        }
        for nm in near_misses if nm["passes_volume"]
    ][:config.RADAR_SIZE]
    meta = {
        "api_ok": api_ok, "scanned_symbols": len(enriched), "near_misses": near_misses[:3],
        "radar": radar,
        "candidates_before_persistence": 0, "candidates_after_persistence": 0,
        "candidates_after_volatility": 0,
    }

    candidates = []
    for sym, e in enriched.items():
        mkt = market[sym]
        if abs(e["hourly_rate"]) < config.MIN_FUNDING_RATE:
            continue
        if mkt["volume_usdt"] < config.MIN_VOLUME_USDT:
            continue
        time_to_funding_ms = rates[sym]["next_funding_time"] - now_ms
        if time_to_funding_ms < 0 or time_to_funding_ms > max_catchable_ms:
            continue
        candidates.append(sym)

    if not candidates:
        return [], meta
    meta["candidates_before_persistence"] = len(candidates)

    signals = []
    for sym in candidates:
        rate = rates[sym]
        mkt = market[sym]
        interval_h = enriched[sym]["interval_h"]
        funding_rate = enriched[sym]["hourly_rate"]  # hourly-equivalent; used for all scoring below
        funding_rate_raw = rate["funding_rate"]  # what's actually paid at next_funding_time

        history = fetch_funding_history(sym)
        persistence = analyze_persistence(funding_rate_raw, history)
        if not persistence["persistent"]:
            time.sleep(0.1)
            continue
        meta["candidates_after_persistence"] += 1

        capture = estimate_multi_period_capture(interval_h, rate["next_funding_time"], now_ms)

        vol = fetch_volatility(sym)
        # A zero reading means a klines call failed. Volatility is the ranking
        # denominator below, so an unmeasured coin would otherwise jump to the top.
        if not vol["vol_1h"] or not vol["vol_15m"] or vol["vol_1h"] >= config.MAX_VOLATILITY:
            time.sleep(0.1)
            continue
        meta["candidates_after_volatility"] += 1

        oi_qty = fetch_open_interest(sym)
        oi_usdt = oi_qty * mkt["last_price"]
        # Cascade detection is off: /fapi/v1/forceOrders only serves the signed-in
        # account's own liquidations, so unsigned it 401'd on every candidate and a
        # cascade never fired. Market-wide liquidations only come over the
        # !forceOrder@arr websocket stream, which a cron-invoked function can't hold.
        cascade = {"detected": False, "direction": None, "count": 0, "total_usdt": 0}
        direction = determine_direction(funding_rate, cascade, mkt["price_change_24h"])
        risk = calculate_risk_score(vol["combined"], funding_rate, mkt["volume_usdt"], cascade, oi_usdt)
        hold_min = max(calculate_hold_time(vol["combined"], cascade), capture["hold_min"])
        funding_earn_per_100 = abs(funding_rate_raw) * 100
        est_total_funding_earn = funding_earn_per_100 * capture["payments_catchable"]
        # Rank by expected capture across the whole planned hold per unit of price
        # noise. Volatility used to be added as a bonus, which put the wildest coins
        # first even though their swings dwarf the funding being collected.
        strength = est_total_funding_earn * 100 / vol["combined"]

        time_to_funding_min = max(0, (rate["next_funding_time"] - now_ms) / 60000)

        signals.append({
            "symbol": sym.replace("USDT", ""),
            "direction": direction,
            "funding_rate": funding_rate * 100,
            "funding_rate_raw": funding_rate_raw * 100,
            "funding_interval_h": interval_h,
            "funding_earn": funding_earn_per_100,
            "funding_catchable": time_to_funding_min <= hold_min,
            "persistence_ratio": persistence["ratio"],
            "payments_catchable": capture["payments_catchable"],
            "est_total_funding_earn": round(est_total_funding_earn, 4),
            "price_change_24h": mkt["price_change_24h"],
            "volatility": round(vol["combined"], 2),
            "vol_15m": round(vol["vol_15m"], 2),
            "vol_1h": round(vol["vol_1h"], 2),
            "volume_m": round(mkt["volume_usdt"] / 1_000_000, 1),
            "oi_m": round(oi_usdt / 1_000_000, 1),
            "cascade": cascade["detected"],
            "cascade_dir": cascade.get("direction", ""),
            "cascade_count": cascade.get("count", 0),
            "cascade_usdt": cascade.get("total_usdt", 0),
            "risk_score": risk,
            "hold_min": hold_min,
            "strength": round(strength, 2),
            "last_price": mkt["last_price"],
            "mark_price": rate["mark_price"],
            "next_funding": rate["next_funding_time"],
            "features": {
                **fetch_context_features(sym),
                "volatility": round(vol["combined"], 3),
                "price_change_24h_pct": mkt["price_change_24h"],
                "oi_usdt_m": round(oi_usdt / 1_000_000, 2),
                "persistence_magnitude_ratio": persistence["magnitude_ratio"],
                "cascade": cascade["detected"],
            },
        })

        time.sleep(0.15)

    signals.sort(key=lambda x: x["strength"], reverse=True)
    return signals[:config.TOP_N_SIGNALS], meta


def next_funding_countdown(next_ts: int) -> str:
    """Time until next funding payment."""
    if next_ts == 0:
        return "?"
    now = int(time.time() * 1000)
    diff_sec = max(0, (next_ts - now) / 1000)
    mins = int(diff_sec / 60)
    secs = int(diff_sec % 60)
    return f"{mins}m{secs:02d}s"
