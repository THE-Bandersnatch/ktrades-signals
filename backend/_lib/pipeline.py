#!/usr/bin/env python3
"""
pipeline.py — one full scan-and-broadcast pass.

Shared by api/scan.py (cron-triggered) and api/telegram-webhook.py
(/scan command) so both take the exact same path: generate signals,
post them as a watchlist, run the confirmation checks on the top 3, post
a card for each.
"""
import time
from datetime import datetime

from . import chart_analysis
from . import config
from . import risk_checks
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

    Returns counts plus the risk sources' health (risk_errors) and each
    analyzed coin's news check, so the cron's log shows whether those
    sources answered from the deployment's network.
    """
    chat_id = config.TELEGRAM_CHAT_ID
    started = time.monotonic()
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

    # Risk gate: Binance flags and the 7/30-day move for every signal (shown
    # in the watchlist), news for the three that get analyzed.
    ctx = risk_checks.load_context() if signals else {"errors": {}}
    for signal in signals:
        signal["risk_checks"] = risk_checks.assess(signal, ctx)
        signal["risk_flags"] = [text for ok, text in signal["risk_checks"] if not ok]

    # Chart analysis runs before anything is posted so that every signal is
    # logged first and posted only if this scan logged it: when an overlapping
    # scan (cron + /scan) logged the same coin a moment earlier, that scan
    # keeps it instead of both posting the same trade. The three analyzed are
    # the scanner's top three, flagged or not: the risk gate may veto one,
    # but promoting the next coin in its place would let the gate add trades.
    top = signals[:3]
    cards = {}
    news_checks = {}
    for signal in top:
        # Each analysis can wait on Binance and two news feeds. Past the budget,
        # the rest go unanalyzed (no card) rather than risk the serverless time
        # limit cutting the scan off before anything is logged or posted.
        if time.monotonic() - started > config.SCAN_SOFT_DEADLINE_S:
            print(f"[Pipeline] {config.SCAN_SOFT_DEADLINE_S}s budget spent; not analyzing {signal['symbol']}")
            break
        # An exception here used to escape after the signals message had already
        # gone out, so none of the scan's signals were ever logged. Skip just the
        # one symbol instead.
        try:
            news = risk_checks.news_check(signal["symbol"], ctx)
            news_checks[signal["symbol"]] = news
            analysis = chart_analysis.analyze_chart(
                signal["symbol"],
                signal["direction"],
                signal["funding_rate"] / 100,
                signal.get("est_total_funding_earn"),
                extra_checks=signal["risk_checks"] + [news],
            )
        except Exception as e:
            print(f"[Pipeline] chart analysis failed for {signal['symbol']}: {e}")
            continue
        cards[signal["symbol"]] = analysis

    # Log every signal, chart-analyzed or not — comparing confirmed vs.
    # unconfirmed outcomes later is the only way to tell whether the
    # confirmation step actually adds value. No indicators means the candles
    # never loaded: logged as not analyzed rather than as analyzed and
    # rejected. Every check's result goes into features, so a rejection can
    # be reconstructed later (v4 kept no record of why BLUR was rejected).
    logged = []
    rows = {}
    unlogged = set()
    for signal in signals:
        analysis = cards.get(signal["symbol"])
        chart = analysis if analysis is not None and "indicators" in analysis else None
        features = signal.setdefault("features", {})
        features["risk_flags"] = signal["risk_flags"]
        if analysis is not None:
            features["checks"] = analysis["details"]
            features["rr_ratio"] = analysis.get("rr_ratio")
        result = track_record.log_signal(signal, scan_count, chart)
        if result is False:
            skipped.append(signal["symbol"])
            continue
        if result is None:
            # Database down: the coin still shows in the watchlist, but no
            # trade card goes out for a trade the track record can't follow.
            unlogged.add(signal["symbol"])
        else:
            rows[signal["symbol"]] = result
        logged.append(signal)
    signals = logged
    logged_symbols = {s["symbol"] for s in logged}
    top = [s for s in top if s["symbol"] in logged_symbols]
    meta["skipped_open"] = skipped

    report = {"risk_errors": ctx["errors"], "news_checks": {k: v[1] for k, v in news_checks.items()}}

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
        return {"signals": 0, "confirmed": 0, **report}

    telegram.send_message(chat_id, telegram.format_signals_message(signals, scan_count, meta))

    confirmed_count = 0
    if top:
        telegram.send_message(
            chat_id, f"\n🔍 <b>Checking the top {len(top)} for a trade...</b>"
        )
    for signal in top:
        if signal["symbol"] not in cards:
            continue
        if signal["symbol"] in unlogged:
            telegram.send_message(
                chat_id,
                f"⛔ <b>NO TRADE — {signal['symbol']}</b>\n"
                "  ❌ The track record database didn't answer, so no trade is posted this scan.",
            )
            continue
        analysis, row = cards[signal["symbol"]], rows[signal["symbol"]]
        # Formatted only now, from the logged row's timestamps, so the card's
        # entry window and exit deadline are the ones the resolver scores.
        try:
            message = chart_analysis.format_analysis_telegram(
                signal["symbol"], analysis, signal, now=row["created_at"], close_by=row["resolve_at"])
        except Exception as e:
            print(f"[Pipeline] card formatting failed for {signal['symbol']}: {e}")
            continue
        telegram.send_message(chat_id, message)
        if analysis.get("confirmed"):
            confirmed_count += 1

    if confirmed_count == 0:
        telegram.send_message(chat_id, "\n⏳ <b>No trade this scan.</b> Nothing above is a trade.")
    else:
        telegram.send_message(
            chat_id, f"\n✅ <b>{confirmed_count} trade{'s' if confirmed_count != 1 else ''} above</b> "
                     f"(🎯 cards only)."
        )

    track_record.record_scan(meta, len(signals), confirmed_count)

    return {
        "signals": len(signals),
        "confirmed": confirmed_count,
        **report,
    }
