#!/usr/bin/env python3
"""
api/telegram-webhook.py — Telegram webhook receiver.

Replaces the long-polling loop in the original telegram_bot.py
(long-polling can't run on serverless). Point Telegram's webhook at
this URL via setWebhook with `secret_token` set to
TELEGRAM_WEBHOOK_SECRET so we can verify calls actually come from
Telegram.

Every command broadcasts to the fixed channel (TELEGRAM_CHAT_ID) —
this bot serves one channel, not per-user sessions — matching how
the original bot was actually used.
"""
import json
import time
from http.server import BaseHTTPRequestHandler

from _lib import config
from _lib import telegram
from _lib.pipeline import run_scan_and_broadcast

HELP_TEXT = (
    "🤖 <b>KTRADES Signals bot</b>\n\n"
    "Signals post automatically on a schedule.\n\n"
    "<b>Commands:</b>\n"
    "/scan — Force an immediate scan\n"
    "/status — Bot status\n"
    "/config — Current filter settings\n"
)


def handle_command(cmd: str, sender_chat_id):
    if cmd == "/start" or cmd == "/help":
        telegram.send_message(sender_chat_id, HELP_TEXT)

    elif cmd == "/scan":
        telegram.send_message(sender_chat_id, "🔄 Scanning now — results will post to the channel shortly...")
        scan_id = int(time.time()) // 60
        run_scan_and_broadcast(scan_id)

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


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if config.TELEGRAM_WEBHOOK_SECRET:
            got = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if got != config.TELEGRAM_WEBHOOK_SECRET:
                self._respond(401, {"error": "unauthorized"})
                return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"

        try:
            update = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid json"})
            return

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
        self._respond(200, {"ok": True})

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)
