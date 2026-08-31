#!/usr/bin/env python3
"""
pipeline.py — one full scan-and-broadcast pass.

Shared by api/scan.py (cron-triggered) and api/telegram-webhook.py
(/scan command) so both take the exact same path: generate signals,
post them, run chart confirmation on the top 3, post those too.
"""
from . import chart_analysis
from . import config
from . import scanner
from . import telegram


def run_scan_and_broadcast(scan_count: int = 1) -> dict:
    """Run one scan pass and broadcast results to the configured channel."""
    chat_id = config.TELEGRAM_CHAT_ID
    signals = scanner.generate_signals()

    msg = telegram.format_signals_message(signals, scan_count)
    telegram.send_message(chat_id, msg)

    confirmed_count = 0
    if signals:
        top = signals[:3]
        telegram.send_message(
            chat_id, f"\n🔍 <b>Running chart analysis on top {len(top)} signals...</b>"
        )
        for signal in top:
            analysis = chart_analysis.analyze_chart(
                signal["symbol"],
                signal["direction"],
                signal["funding_rate"] / 100,
            )
            telegram.send_message(
                chat_id,
                chart_analysis.format_analysis_telegram(signal["symbol"], analysis, signal),
            )
            if analysis.get("confirmed"):
                confirmed_count += 1

        if confirmed_count == 0:
            telegram.send_message(chat_id, "\n⏳ No confirmed trades this scan. Monitoring...")
        else:
            telegram.send_message(chat_id, f"\n✅ <b>{confirmed_count} trade(s) confirmed above!</b>")

    return {
        "signals": len(signals),
        "confirmed": confirmed_count,
    }
