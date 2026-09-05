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
from _lib.pipeline import run_scan_and_broadcast

app = Flask(__name__)

HELP_TEXT = (
    "🤖 <b>KTRADES Signals bot</b>\n\n"
    "Signals post automatically on a schedule.\n\n"
    "<b>Commands:</b>\n"
    "/scan — Force an immediate scan\n"
    "/status — Bot status\n"
    "/config — Current filter settings\n"
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


def handle_command(cmd: str, sender_chat_id):
    if cmd in ("/start", "/help"):
        telegram.send_message(sender_chat_id, HELP_TEXT)

    elif cmd == "/scan":
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
        cmd = text.split()[0].lower()
        try:
            handle_command(cmd, sender_chat_id)
        except Exception as e:
            telegram.send_message(sender_chat_id, f"⚠️ Error: {e}")

    # Always 200 — Telegram retries on non-2xx.
    return jsonify({"ok": True})
