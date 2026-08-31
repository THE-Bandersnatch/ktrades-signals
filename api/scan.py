#!/usr/bin/env python3
"""
api/scan.py — one-shot scan endpoint.

Triggered by the GitHub Actions cron (every ~5 min, see
.github/workflows/scan.yml) and, as a native fallback, once a day
by Vercel's own cron (see vercel.json). Requires the X-Scan-Secret
header to match the SCAN_SECRET env var so it can't be triggered by
anyone who finds the URL.
"""
import json
import time
from http.server import BaseHTTPRequestHandler

from _lib import config
from _lib.pipeline import run_scan_and_broadcast


class handler(BaseHTTPRequestHandler):
    def _run(self):
        # Accept either our own header (used by the GitHub Actions cron) or
        # a Bearer token (Vercel's native cron auto-sends `Authorization:
        # Bearer $CRON_SECRET` when an env var named CRON_SECRET is set —
        # set it to the same value as SCAN_SECRET).
        header_secret = self.headers.get("X-Scan-Secret", "")
        auth = self.headers.get("Authorization", "")
        bearer_secret = auth[7:] if auth.startswith("Bearer ") else ""

        if not config.SCAN_SECRET or config.SCAN_SECRET not in (header_secret, bearer_secret):
            self._respond(401, {"error": "unauthorized"})
            return

        if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
            self._respond(500, {"error": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not configured"})
            return

        try:
            scan_id = int(time.time()) // 60
            result = run_scan_and_broadcast(scan_id)
            self._respond(200, {"ok": True, **result})
        except Exception as e:
            self._respond(500, {"error": str(e)})

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._run()

    def do_POST(self):
        self._run()
