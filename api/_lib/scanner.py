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
    """Safe GET request to Binance API with rate limit handling."""
    try:
        url = f"{config.BASE_URL}{endpoint}"
        r = SESSION.get(url, params=params, timeout=10)
        if r.status_code == 429:
            time.sleep(30)
            return None
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def fetch_1h_funding_coins() -> dict:
    """Get all coins that have 1-hour funding intervals."""
    data = api_get("/fapi/v1/fundingInfo")
    if not data:
        return {}

    coins = {}
    for item in data:
        interval = item.get("fundingIntervalHours", 8)
        if interval == config.FUNDING_INTERVAL_H:
            symbol = item["symbol"]
            coins[symbol] = {
                "symbol": symbol,
                "funding_interval": interval,
                "funding_cap": float(item.get("fundingRateCap", 0.03)),
                "funding_floor": float(item.get("fundingRateFloor", -0.03)),
            }
    return coins


def fetch_funding_rates(symbols: list) -> dict:
    """Get current funding rates and mark prices for given symbols."""
    data = api_get("/fapi/v1/premiumIndex")
    if not data:
        return {}

    rates = {}
    symbol_set = set(symbols)
    for item in data:
        sym = item["symbol"]
        if sym in symbol_set:
            rates[sym] = {
                "funding_rate": float(item.get("lastFundingRate", 0)),
                "mark_price": float(item.get("markPrice", 0)),
                "next_funding_time": int(item.get("nextFundingTime", 0)),
                "index_price": float(item.get("indexPrice", 0)),
            }
    return rates


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
    """Calculate volatility from 15m and 1h klines."""
    result = {"vol_1h": 0, "vol_15m": 0, "combined": 0}

    klines_1h = api_get("/fapi/v1/klines", {
        "symbol": symbol, "interval": "1h", "limit": config.VOLATILITY_PERIOD_1H
    })
    if klines_1h and len(klines_1h) >= 2:
        ranges = []
        for k in klines_1h:
            h, l, c = float(k[2]), float(k[3]), float(k[4])
            if c > 0:
                ranges.append((h - l) / c * 100)
        result["vol_1h"] = sum(ranges) / len(ranges) if ranges else 0

    klines_15m = api_get("/fapi/v1/klines", {
        "symbol": symbol, "interval": "15m", "limit": config.VOLATILITY_PERIOD_15M
    })
    if klines_15m and len(klines_15m) >= 2:
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


def fetch_liquidations(symbol: str) -> list:
    """Get recent forced liquidations for a symbol."""
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

def generate_signals() -> list:
    """Main signal generation pipeline."""

    coins_1h = fetch_1h_funding_coins()
    if not coins_1h:
        return []
    symbols = list(coins_1h.keys())

    rates = fetch_funding_rates(symbols)
    market = fetch_market_data(symbols)

    candidates = []
    for sym in symbols:
        if sym not in rates or sym not in market:
            continue

        rate = rates[sym]
        mkt = market[sym]

        if abs(rate["funding_rate"]) < config.MIN_FUNDING_RATE:
            continue
        if mkt["volume_usdt"] < config.MIN_VOLUME_USDT:
            continue

        candidates.append(sym)

    if not candidates:
        return []

    signals = []
    for sym in candidates:
        rate = rates[sym]
        mkt = market[sym]
        funding_rate = rate["funding_rate"]

        vol = fetch_volatility(sym)
        oi_qty = fetch_open_interest(sym)
        oi_usdt = oi_qty * mkt["last_price"]
        liqs = fetch_liquidations(sym)
        cascade = detect_cascade(liqs)
        direction = determine_direction(funding_rate, cascade, mkt["price_change_24h"])
        risk = calculate_risk_score(vol["combined"], funding_rate, mkt["volume_usdt"], cascade, oi_usdt)
        hold_min = calculate_hold_time(vol["combined"], cascade)
        funding_earn_per_100 = abs(funding_rate) * 100
        strength = (abs(funding_rate) * 10000) + (vol["combined"] * 5) + (20 if cascade["detected"] else 0)

        signals.append({
            "symbol": sym.replace("USDT", ""),
            "direction": direction,
            "funding_rate": funding_rate * 100,
            "funding_earn": funding_earn_per_100,
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
        })

        time.sleep(0.15)

    signals.sort(key=lambda x: x["strength"], reverse=True)
    return signals[:config.TOP_N_SIGNALS]


def next_funding_countdown(next_ts: int) -> str:
    """Time until next funding payment."""
    if next_ts == 0:
        return "?"
    now = int(time.time() * 1000)
    diff_sec = max(0, (next_ts - now) / 1000)
    mins = int(diff_sec / 60)
    secs = int(diff_sec % 60)
    return f"{mins}m{secs:02d}s"
