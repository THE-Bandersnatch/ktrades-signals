# ═══════════════════════════════════════════════════
#  Config — credentials come from env vars (Vercel
#  dashboard / .env.local), everything else is a tunable
#  constant carried over from the original bot.
# ═══════════════════════════════════════════════════
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SCAN_SECRET = os.environ.get("SCAN_SECRET", "")
# Set via setWebhook's `secret_token` param; Telegram echoes it back in the
# X-Telegram-Bot-Api-Secret-Token header on every webhook call so we can
# confirm a request actually came from Telegram.
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Binance Futures API base
BASE_URL = "https://fapi.binance.com"

# ── Scan settings ─────────────────────────────────
TOP_N_SIGNALS = 15

# ── Funding filters ───────────────────────────────
MIN_FUNDING_RATE = 0.0005  # 0.05% minimum absolute funding rate
FUNDING_INTERVAL_H = 1  # only 1-hour funding coins

# ── Volume / Liquidity filters ────────────────────
MIN_VOLUME_USDT = 5_000_000  # minimum 24h volume in USDT
MIN_OI_USDT = 2_000_000  # minimum open interest in USDT

# ── Volatility ────────────────────────────────────
VOLATILITY_PERIOD_1H = 4  # number of 1h candles for volatility calc
VOLATILITY_PERIOD_15M = 8  # number of 15m candles for volatility calc
MIN_VOLATILITY_SCORE = 0.5  # minimum combined volatility score (0-100)

# ── Liquidation cascade detection ─────────────────
CASCADE_WINDOW_MIN = 5  # look back N minutes for liquidation clusters
CASCADE_MIN_COUNT = 3  # minimum liquidations to trigger cascade alert
CASCADE_MIN_USDT = 50_000  # minimum total liquidation value for cascade

# ── Risk parameters ───────────────────────────────
MAX_RISK_SCORE = 85  # max risk score (0-100) before warning
SUGGESTED_HOLD_MIN = 15  # default suggested hold time (minutes)
SUGGESTED_HOLD_MAX = 60  # max hold time suggestion
