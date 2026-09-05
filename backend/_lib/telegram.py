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

    raw_sign = "+" if signal["funding_rate_raw"] > 0 else ""
    interval_h = signal["funding_interval_h"]
    catch_note = "" if signal["funding_catchable"] else " ⚠️ may pay out after your hold window"

    payments = signal["payments_catchable"]
    multi_note = (
        f"\n  🔁 Persistent ({signal['persistence_ratio']*100:.0f}% of last "
        f"{config.PERSISTENCE_HISTORY_COUNT} payments) — plan for {payments}x payout"
        f"{'s' if payments != 1 else ''} (~${signal['est_total_funding_earn']:.4f} total per $100)"
    )

    return (
        f"<b>#{rank} {signal['symbol']}</b> — {direction_emoji}\n"
        f"  💰 Funding: <b>{raw_sign}{signal['funding_rate_raw']:.4f}%/{interval_h}h</b>"
        f" (${signal['funding_earn']:.4f} per $100, {funding_sign}{signal['funding_rate']:.4f}%/hr equiv.)"
        f"{catch_note}"
        f"{multi_note}\n"
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


def format_track_record(stats: dict) -> str:
    """Format aggregate signal-outcome stats for Telegram."""

    def fmt_bucket(b):
        if b["count"] == 0:
            return "no resolved signals yet"
        win = f"{b['win_rate']:.0f}%" if b["win_rate"] is not None else "n/a"
        avg = f"{b['avg_pct']:+.2f}%" if b["avg_pct"] is not None else "n/a"
        return f"{b['count']} resolved, {b['tp']}W/{b['sl']}L ({win} win rate), avg {avg}/trade"

    return (
        f"📈 <b>Track Record</b> — last {stats['days']}d\n\n"
        f"Logged: {stats['total']}  |  Pending: {stats['pending']}  |  Resolved: {stats['resolved']}\n\n"
        f"<b>Overall:</b> {fmt_bucket(stats['overall'])}\n"
        f"<b>Chart-confirmed:</b> {fmt_bucket(stats['confirmed'])}\n"
        f"<b>Analyzed, rejected:</b> {fmt_bucket(stats['rejected'])}\n"
        f"<b>Not analyzed (rank &gt;3):</b> {fmt_bucket(stats['not_analyzed'])}\n\n"
        f"<i>Win rate = TP vs SL only, excludes expired/no-data outcomes.</i>"
    )


def format_signals_message(signals: list, count: int, meta: dict = None) -> str:
    """Format all signals into a single Telegram message."""
    now = datetime.now().strftime("%H:%M:%S")

    if not signals:
        meta = meta or {}
        scanned = meta.get("scanned_symbols", 0)
        near_misses = meta.get("near_misses", [])

        if near_misses:
            miss_lines = []
            for nm in near_misses:
                sign = "+" if nm["funding_rate_pct"] > 0 else ""
                vol_ok = "✓" if nm["passes_volume"] else "✗"
                miss_lines.append(
                    f"  {nm['symbol']}: {sign}{nm['funding_rate_pct']:.4f}%"
                    f"  |  Vol: ${nm['volume_m']}M {vol_ok}"
                )
            closest_block = "Closest (hourly-equivalent):\n" + "\n".join(miss_lines)
        else:
            closest_block = "No symbols could be scanned this cycle."

        before = meta.get("candidates_before_persistence", 0)
        after = meta.get("candidates_after_persistence", 0)
        persistence_note = ""
        if before > 0 and after == 0:
            persistence_note = (
                f"\n\n{before} coin(s) cleared the funding/volume/timing bar, but none showed "
                f"sustained history (single-print spikes only) — see /config for the persistence bar."
            )

        return (
            f"📊 <b>Scan #{count}</b> — {now}\n\n"
            f"No signals matching criteria.\n"
            f"Scanned {scanned} coin(s) across all funding intervals.\n"
            f"{closest_block}"
            f"{persistence_note}\n\n"
            f"Filters: min {config.MIN_FUNDING_RATE * 100:.2f}%/hr-equivalent funding, "
            f"min ${config.MIN_VOLUME_USDT / 1_000_000:.0f}M volume, "
            f"payout within {config.SUGGESTED_HOLD_MAX}min"
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
        f"Avg Funding (hr-equiv): {avg_funding:.4f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    signal_texts = [format_signal_telegram(s, i + 1) for i, s in enumerate(signals)]

    footer = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Signals only — not financial advice</i>"
    )

    return header + "\n\n" + "\n\n".join(signal_texts) + "\n\n" + footer
