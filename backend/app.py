#!/usr/bin/env python3
"""
app.py — Flask entrypoint for the backend service.

Vercel Services requires an explicit ASGI/WSGI entrypoint for a Python
service (the older per-file /api convention isn't auto-detected inside
a services-mode deployment), so this replaces the earlier
api/scan.py + api/telegram-webhook.py file-based functions with a
single small Flask app exposing the same two routes.
"""
import json
import time

from flask import Flask, request, jsonify

from _lib import config
from _lib import telegram
from _lib import track_record
from _lib.pipeline import run_scan_and_broadcast

app = Flask(__name__)

HELP_TEXT = (
    "🤖 <b>KTRADES Signals bot</b>\n\n"
    "Signals post automatically on a schedule.\n\n"
    "<b>Commands:</b>\n"
    "/scan — Force an immediate scan\n"
    "/status — Bot status\n"
    "/config — Current filter settings\n"
    "/track [days] — Signal track record (default 30d)\n"
)


@app.route("/api/scan", methods=["GET", "POST"])
def scan():
    # Accept either our own header (used by the GitHub Actions cron) or a
    # Bearer token (Vercel's native cron auto-sends `Authorization: Bearer
    # $CRON_SECRET` when an env var named CRON_SECRET is set).
    header_secret = request.headers.get("X-Scan-Secret", "")
    auth = request.headers.get("Authorization", "")
    bearer_secret = auth[7:] if auth.startswith("Bearer ") else ""

    if not config.SCAN_SECRET or config.SCAN_SECRET not in (header_secret, bearer_secret):
        return jsonify({"error": "unauthorized"}), 401

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return jsonify({"error": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not configured"}), 500

    try:
        scan_id = int(time.time()) // 60
        result = run_scan_and_broadcast(scan_id)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _public_json(payload, max_age: int = 15):
    """Public read-only response, briefly cached at Vercel's edge so a busy
    live page doesn't open a database connection per viewer per poll."""
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = f"public, s-maxage={max_age}, stale-while-revalidate={max_age * 4}"
    return resp


@app.route("/api/signals", methods=["GET"])
def recent_signals():
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
    except ValueError:
        limit = 50
    trades_only = request.args.get("scope") == "trades"
    status = request.args.get("status", "all")
    if status not in ("all", "open", "closed"):
        status = "all"
    try:
        return _public_json({"signals": track_record.get_recent_signals(limit, trades_only, status)})
    except Exception as e:
        print(f"[API] /api/signals failed: {e}")
        return jsonify({"error": "unavailable"}), 503


@app.route("/api/status", methods=["GET"])
def scanner_status():
    try:
        return _public_json(track_record.get_scanner_status())
    except Exception as e:
        print(f"[API] /api/status failed: {e}")
        return jsonify({"error": "unavailable"}), 503


@app.route("/api/stats", methods=["GET"])
def public_stats():
    try:
        days = max(1, min(int(request.args.get("days", 30)), 365))
    except ValueError:
        days = 30
    try:
        stats = track_record.get_stats(days)
    except Exception as e:
        print(f"[API] /api/stats failed: {e}")
        return jsonify({"error": "unavailable"}), 503
    # The public page shows the signals' own record; the inverse comparison
    # stays in the admin /track command.
    public = {k: v for k, v in stats.items() if not k.startswith("inverse_")}
    return _public_json(public, max_age=60)


def handle_command(cmd: str, sender_chat_id, args: str = ""):
    if cmd in ("/start", "/help"):
        telegram.send_message(sender_chat_id, HELP_TEXT)

    elif cmd == "/scan":
        # A scan broadcasts to the public channel — only admins may force one.
        if sender_chat_id not in config.ADMIN_CHAT_IDS:
            telegram.send_message(
                sender_chat_id,
                "🔒 /scan is admin-only. Signals post to the channel automatically.",
            )
            print(f"[Webhook] Refused /scan from chat {sender_chat_id} — add it to ADMIN_CHAT_IDS if it's yours")
            return
        telegram.send_message(sender_chat_id, "🔄 Scanning now — results will post to the channel shortly...")
        scan_id = int(time.time()) // 60
        run_scan_and_broadcast(scan_id, force_notify=True)

    elif cmd == "/status":
        telegram.send_message(
            sender_chat_id,
            "📊 <b>Bot Status</b>\n\n"
            "Status: 🟢 Running (scheduled scans)\n"
            "Use /scan for an immediate scan.",
        )

    elif cmd == "/config":
        telegram.send_message(
            sender_chat_id,
            "⚙️ <b>Current Filters</b>\n\n"
            f"Min Funding Rate: {config.MIN_FUNDING_RATE * 100:.2f}%\n"
            f"Min Volume: ${config.MIN_VOLUME_USDT:,.0f}\n"
            f"Min Open Interest: ${config.MIN_OI_USDT:,.0f}\n"
            f"Top Signals: {config.TOP_N_SIGNALS}\n"
            f"Cascade Min Count: {config.CASCADE_MIN_COUNT}\n"
            f"Cascade Min Value: ${config.CASCADE_MIN_USDT:,.0f}",
        )

    elif cmd == "/track":
        # Includes the inverse-strategy comparison — admin-only, like /scan.
        if sender_chat_id not in config.ADMIN_CHAT_IDS:
            telegram.send_message(sender_chat_id, "🔒 /track is admin-only. See the live track record on the website.")
            return
        try:
            days = int(args.strip()) if args.strip() else 30
        except ValueError:
            days = 30
        days = max(1, min(days, 365))
        stats = track_record.get_stats(days)
        telegram.send_message(sender_chat_id, telegram.format_track_record(stats))

    else:
        telegram.send_message(sender_chat_id, HELP_TEXT)


@app.route("/api/telegram-webhook", methods=["POST"])
def telegram_webhook():
    if config.TELEGRAM_WEBHOOK_SECRET:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != config.TELEGRAM_WEBHOOK_SECRET:
            return jsonify({"error": "unauthorized"}), 401

    try:
        update = request.get_json(force=True, silent=True) or {}
    except json.JSONDecodeError:
        return jsonify({"error": "invalid json"}), 400

    msg = update.get("message", {})
    sender_chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    if sender_chat_id and text:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        try:
            handle_command(cmd, sender_chat_id, args)
        except Exception as e:
            telegram.send_message(sender_chat_id, f"⚠️ Error: {e}")

    # Always 200 — Telegram retries on non-2xx.
    return jsonify({"ok": True})
