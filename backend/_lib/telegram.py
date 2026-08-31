#!/usr/bin/env python3
"""
telegram.py — Telegram send + message formatting.

Ported from BINANCE/telegram_bot.py, minus the long-polling loop
(that can't run on serverless — see api/telegram-webhook.py) and
minus the in-memory auto_scan state (each Vercel invocation is
stateless; the GitHub Actions cron is what makes scanning
"automatic" now).
"""
from datetime import datetime

import requests

from . import config
from . import scanner

TG_BASE = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def tg_request(method: str, data: dict = None, timeout: int = 20):
    """Send a request to the Telegram Bot API."""
    try:
        r = requests.post(f"{TG_BASE}/{method}", json=data, timeout=timeout)
        return r.json()
    except Exception as e:
        print(f"[TG Error] {e}")
        return None


def send_message(chat_id, text: str, parse_mode: str = "HTML"):
    """Send a message to a Telegram chat, splitting on Telegram's 4096-char limit."""
    chunks = []
    while len(text) > 4000:
        split_at = text.rfind("\n", 0, 4000)
        if split_at == -1:
            split_at = 4000
        chunks.append(text[:split_at])
        text = text[split_at:]
    chunks.append(text)

    for chunk in chunks:
        tg_request("sendMessage", {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        })


# ═══════════════════════════════════════════════════
#  SIGNAL FORMATTING (Telegram HTML)
# ═══════════════════════════════════════════════════

def format_signal_telegram(signal: dict, rank: int) -> str:
    """Format a single signal for Telegram."""
    direction_emoji = "🟢 LONG" if signal["direction"] == "LONG" else "🔴 SHORT"
    funding_sign = "+" if signal["funding_rate"] > 0 else ""

    if signal["risk_score"] >= 70:
        risk_emoji = "🔴"
    elif signal["risk_score"] >= 40:
        risk_emoji = "🟡"
    else:
        risk_emoji = "🟢"

    cascade_text = ""
    if signal["cascade"]:
        if signal["cascade_dir"] == "LONG_LIQUIDATED":
            cascade_text = f"\n  🔻 <b>CASCADE:</b> Longs wiped ({signal['cascade_count']}x, ${signal['cascade_usdt']:,.0f})"
        else:
            cascade_text = f"\n  🔺 <b>CASCADE:</b> Shorts wiped ({signal['cascade_count']}x, ${signal['cascade_usdt']:,.0f})"

    risk_warning = ""
    if signal["risk_score"] >= 85:
        risk_warning = "\n  ⚠️ <b>EXTREME RISK — Size down!</b>"

    countdown = scanner.next_funding_countdown(signal["next_funding"])

    return (
        f"<b>#{rank} {signal['symbol']}</b> — {direction_emoji}\n"
        f"  💰 Funding: <b>{funding_sign}{signal['funding_rate']:.4f}%</b>"
        f" (${signal['funding_earn']:.4f}/hr per $100)\n"
        f"  💵 Price: ${signal['last_price']:,.4f}"
        f"  |  24h: {'+' if signal['price_change_24h'] > 0 else ''}{signal['price_change_24h']:.1f}%\n"
        f"  📊 Vol: ${signal['volume_m']}M  |  OI: ${signal['oi_m']}M\n"
        f"  📈 Volatility: {signal['volatility']}"
        f" (15m:{signal['vol_15m']} 1h:{signal['vol_1h']})\n"
        f"  {risk_emoji} Risk: {signal['risk_score']}/100"
        f"  |  ⏱ Hold: ~{signal['hold_min']}min"
        f"  |  ⏳ Next: {countdown}"
        f"{cascade_text}{risk_warning}"
    )


def format_signals_message(signals: list, count: int) -> str:
    """Format all signals into a single Telegram message."""
    now = datetime.now().strftime("%H:%M:%S")

    if not signals:
        return (
            f"📊 <b>Scan #{count}</b> — {now}\n\n"
            f"No signals matching criteria.\n"
            f"Filters: 1h funding, min {config.MIN_FUNDING_RATE * 100:.2f}% rate"
        )

    longs = sum(1 for s in signals if s["direction"] == "LONG")
    shorts = len(signals) - longs
    cascades = sum(1 for s in signals if s["cascade"])
    avg_funding = sum(abs(s["funding_rate"]) for s in signals) / len(signals)

    header = (
        f"📊 <b>KTRADES SIGNALS</b>\n"
        f"🕐 {now}  |  Scan #{count}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Longs: {longs}  |  🔴 Shorts: {shorts}"
        f"  |  ⚡ Cascades: {cascades}\n"
        f"Avg Funding: {avg_funding:.4f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    signal_texts = [format_signal_telegram(s, i + 1) for i, s in enumerate(signals)]

    footer = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Signals only — not financial advice</i>"
    )

    return header + "\n\n" + "\n\n".join(signal_texts) + "\n\n" + footer
