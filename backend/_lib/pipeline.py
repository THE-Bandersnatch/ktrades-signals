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
from . import track_record


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
    track_record.resolve_pending_signals()

    # Close the loop for subscribers: every confirmed trade's result gets
    # posted, losses included. Results count as announced only once Telegram
    # accepts the message, so a failed send is retried on the next scan.
    track_record.announce_results(
        lambda rows: telegram.send_message(chat_id, telegram.format_results_message(rows))
    )

    signals, meta = scanner.generate_signals()

    # One open position per coin — don't re-post a symbol whose previous
    # signal is still inside its hold window.
    open_now = track_record.open_symbols()
    skipped = [s["symbol"] for s in signals if s["symbol"] in open_now]
    signals = [s for s in signals if s["symbol"] not in open_now]

    # Chart analysis runs before anything is posted so that every signal is
    # logged first and posted only if this scan logged it: when an overlapping
    # scan (cron + /scan) logged the same coin a moment earlier, that scan
    # keeps it instead of both posting the same trade.
    top = signals[:3]
    cards = {}
    for signal in top:
        # An exception here used to escape after the signals message had already
        # gone out, so none of the scan's signals were ever logged. Skip just the
        # one symbol instead.
        try:
            analysis = chart_analysis.analyze_chart(
                signal["symbol"],
                signal["direction"],
                signal["funding_rate"] / 100,
            )
            message = chart_analysis.format_analysis_telegram(signal["symbol"], analysis, signal)
        except Exception as e:
            print(f"[Pipeline] chart analysis failed for {signal['symbol']}: {e}")
            continue
        cards[signal["symbol"]] = (analysis, message)

    # Log every signal, chart-analyzed or not — comparing confirmed vs.
    # unconfirmed outcomes later is the only way to tell whether the
    # technical-confirmation step actually adds value. No indicators means the
    # candles never loaded: logged as not analyzed rather than as analyzed and
    # rejected. A database failure (None) still posts, as before.
    logged = []
    for signal in signals:
        analysis = cards.get(signal["symbol"], (None, None))[0]
        chart = analysis if analysis is not None and "indicators" in analysis else None
        if track_record.log_signal(signal, scan_count, chart) is False:
            skipped.append(signal["symbol"])
        else:
            logged.append(signal)
    signals = logged
    logged_symbols = {s["symbol"] for s in logged}
    top = [s for s in top if s["symbol"] in logged_symbols]
    meta["skipped_open"] = skipped

    if not signals:
        track_record.record_scan(meta, 0, 0)
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
    if top:
        telegram.send_message(
            chat_id, f"\n🔍 <b>Running chart analysis on top {len(top)} signals...</b>"
        )
    for signal in top:
        if signal["symbol"] not in cards:
            continue
        analysis, message = cards[signal["symbol"]]
        telegram.send_message(chat_id, message)
        if analysis.get("confirmed"):
            confirmed_count += 1

    if confirmed_count == 0:
        telegram.send_message(chat_id, "\n⏳ No confirmed trades this scan. Monitoring...")
    else:
        telegram.send_message(chat_id, f"\n✅ <b>{confirmed_count} trade(s) confirmed above!</b>")

    track_record.record_scan(meta, len(signals), confirmed_count)

    return {
        "signals": len(signals),
        "confirmed": confirmed_count,
    }
