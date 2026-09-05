#!/usr/bin/env python3
"""
pipeline.py — one full scan-and-broadcast pass.

Shared by api/scan.py (cron-triggered) and api/telegram-webhook.py
(/scan command) so both take the exact same path: generate signals,
post them, run chart confirmation on the top 3, post those too.
"""
from datetime import datetime

from . import chart_analysis
from . import config
from . import scanner
from . import telegram


def _is_heartbeat_tick() -> bool:
    """Roughly-once-per-hour check, used to throttle the routine "nothing
    found" case (see EMPTY_SCAN_HEARTBEAT_WINDOW_MIN in config.py)."""
    return datetime.now().minute < config.EMPTY_SCAN_HEARTBEAT_WINDOW_MIN


def run_scan_and_broadcast(scan_count: int = 1, force_notify: bool = False) -> dict:
    """Run one scan pass and broadcast results to the configured channel.

    force_notify=True bypasses the empty-scan heartbeat throttle — used for
    the /scan command, where someone explicitly asked for an answer right
    now and should always get one, unlike the routine cron tick.
    """
    chat_id = config.TELEGRAM_CHAT_ID
    signals, meta = scanner.generate_signals()

    if not signals:
        if force_notify or _is_heartbeat_tick():
            if not meta["api_ok"]:
                telegram.send_message(
                    chat_id,
                    f"⚠️ <b>Scan #{scan_count}</b> — {datetime.now().strftime('%H:%M:%S')}\n"
                    f"Binance funding-info API didn't respond — skipping this scan.",
                )
            else:
                telegram.send_message(
                    chat_id, telegram.format_signals_message(signals, scan_count, meta)
                )
        return {"signals": 0, "confirmed": 0}

    telegram.send_message(chat_id, telegram.format_signals_message(signals, scan_count, meta))

    confirmed_count = 0
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
