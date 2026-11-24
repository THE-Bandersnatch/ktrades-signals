"""
scalp.py — the admin-only /scalp Telegram command.

Reports the live state of the 1-minute RSI<30 bounce setup on ETH and BTC
futures: whether it is active right now, and if so the entry, target, stop and
5-minute exit. It only reads public candles and never places orders.

The rule lost money after fees in a 30-day replay (2026-11-24: ETH, 487 trades,
-0.075% per trade), so every reply says so. A local paper-trade log
(BINANCE_BOT/scalp_watch.py) is measuring it live.
"""
import requests

from . import config

SYMBOLS   = ("ETHUSDT", "BTCUSDT")
RSI_LEN   = 14
RSI_ENTRY = 30
TP_PCT    = 0.15
SL_PCT    = 0.25
HOLD_MIN  = 5
FRESH_BARS = 2          # a cross within the last 2 closed candles still counts
FEE_RT_PCT = 0.08       # taker both ways
EXAMPLE_USD = 500.0     # only for the "what the stop costs" line


def _closed_1m(symbol: str, limit: int = 200):
    r = requests.get(f"{config.BASE_URL}/fapi/v1/klines",
                     params={"symbol": symbol, "interval": "1m", "limit": limit}, timeout=10)
    r.raise_for_status()
    return [float(k[4]) for k in r.json()[:-1]]   # drop the candle still forming


def _rsi(closes, n: int = RSI_LEN):
    out = [50.0] * len(closes)
    ag = al = 0.0
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g, l = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            ag += g / n; al += l / n
        else:
            ag = (ag * (n - 1) + g) / n; al = (al * (n - 1) + l) / n
        if i >= n:
            out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def _fmt(px: float) -> str:
    return f"{px:,.2f}" if px >= 100 else f"{px:,.4f}"


def scalp_report() -> str:
    lines = ["⚡ <b>Scalp check</b> (1m RSI&lt;30 bounce)\n"]
    any_active = False
    for sym in SYMBOLS:
        closes = _closed_1m(sym)
        rsi = _rsi(closes)
        px = closes[-1]
        crossed = any(rsi[-k] < RSI_ENTRY <= rsi[-k - 1] for k in range(1, FRESH_BARS + 1))
        active = crossed and rsi[-1] < RSI_ENTRY + 5
        name = sym.replace("USDT", "")
        if active:
            any_active = True
            stop_cost = EXAMPLE_USD * (SL_PCT + FEE_RT_PCT) / 100
            lines.append(
                f"🟢 <b>{name}: setup active</b> (RSI {rsi[-1]:.0f})\n"
                f"Limit entry ≈ {_fmt(px)}\n"
                f"Target {_fmt(px * (1 + TP_PCT / 100))} (+{TP_PCT}%) · "
                f"Stop {_fmt(px * (1 - SL_PCT / 100))} (−{SL_PCT}%)\n"
                f"Exit after {HOLD_MIN} min whatever happens.\n"
                f"At ${EXAMPLE_USD:.0f} the stop costs ≈ ${stop_cost:.2f} with fees.\n"
            )
        else:
            lines.append(f"⚪ {name}: no setup. RSI {rsi[-1]:.0f}, fires below {RSI_ENTRY}. Price {_fmt(px)}.\n")
    if not any_active:
        lines.append("Nothing to do right now. Waiting is a position.\n")
    lines.append(
        "⚠️ 30-day replay: this rule <b>lost</b> money after fees (ETH −0.075%/trade, 42% wins). "
        "It is being paper-tested. Use 1–2x leverage max, isolated margin, a real stop. Not advice."
    )
    return "\n".join(lines)
