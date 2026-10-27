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
# Comma-separated Telegram chat ids allowed to run /scan, which broadcasts to
# the public channel. Empty = nobody can force a scan from Telegram.
ADMIN_CHAT_IDS = {
    int(x) for x in os.environ.get("ADMIN_CHAT_IDS", "").replace(" ", "").split(",") if x
}
# Pooled connection — this is a serverless function, use the -pooler host.
# Schema DDL (schema.sql) is applied manually with DATABASE_URL_UNPOOLED;
# the app itself never runs migrations.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Binance Futures API base
BASE_URL = "https://fapi.binance.com"

# ── Scan settings ─────────────────────────────────
TOP_N_SIGNALS = 15
# Bump whenever signal-generation rules change, so the track record can
# compare versions instead of blending them.
#   1 — original funding fade + chart confirmation
#   2 — no re-signal on a symbol whose previous signal is still open
#   3 — closed candles only, 1h volatility cap, funding-per-volatility ranking,
#       ATR-only stops with a minimum R:R, cascade detection disabled
STRATEGY_VERSION = "3"
# Matches the GitHub Actions cron (.github/workflows/scan.yml); only used to
# tell site visitors roughly when the next scan lands.
SCAN_INTERVAL_MIN = 30
RADAR_SIZE = 8
# Public site, linked from Telegram posts.
SITE_URL = os.environ.get("PUBLIC_SITE_URL", "https://ktrades-signals.vercel.app")

# ── Funding filters ───────────────────────────────
# Compared against each symbol's HOURLY-EQUIVALENT rate (raw rate / its
# funding interval), not the raw per-payment rate — this is what makes an
# 8h-interval coin at -0.40%/8h and a 1h-interval coin at -0.05%/hr count as
# equally "extreme," instead of only ever scanning the 1h bucket.
MIN_FUNDING_RATE = 0.0005  # 0.05%/hr-equivalent minimum absolute funding rate
DEFAULT_FUNDING_INTERVAL_H = 8  # Binance's standard interval for symbols with no /fundingInfo override

# ── Volume / Liquidity filters ────────────────────
MIN_VOLUME_USDT = 5_000_000  # minimum 24h volume in USDT
MIN_OI_USDT = 2_000_000  # minimum open interest in USDT

# ── Volatility ────────────────────────────────────
VOLATILITY_PERIOD_1H = 4  # number of 1h candles for volatility calc
VOLATILITY_PERIOD_15M = 8  # number of 15m candles for volatility calc
MIN_VOLATILITY_SCORE = 0.5  # minimum combined volatility score (0-100)
# Skip a candidate whose average 1h candle range (vol_1h, % of price, over the
# last VOLATILITY_PERIOD_1H closed candles) is at or above this. In the 200
# signals resolved 2026-09-22..10-26, the 3 posted trades above it (BIRB,
# IOST, ORDER) accounted for 67% of the posted trades' total net loss.
MAX_VOLATILITY = 8.0

# ── Liquidation cascade detection ─────────────────
CASCADE_WINDOW_MIN = 5  # look back N minutes for liquidation clusters
CASCADE_MIN_COUNT = 3  # minimum liquidations to trigger cascade alert
CASCADE_MIN_USDT = 50_000  # minimum total liquidation value for cascade

# ── Funding persistence (multi-period capture) ────
# A single extreme funding print is often noise — worth roughly one fee's
# width, not a strategy. These check the symbol's own recent payment
# history to require the crowding be sustained, then estimate how many
# consecutive payments are realistically catchable in one extended hold.
# Shorter-interval (1h) coins fit more payments in the same budget, which
# is what makes them worth more than a flat "prefer 1h" rule would capture.
PERSISTENCE_HISTORY_COUNT = 8  # how many past payments to check
PERSISTENCE_MIN_RATIO = 0.75  # fraction of history that must agree in direction
PERSISTENCE_MIN_MAGNITUDE_RATIO = 0.4  # avg magnitude of agreeing history vs current rate
PERSISTENCE_MAX_HOLD_MIN = 240  # outer bound (minutes) for a multi-period hold

# ── Track record costs ────────────────────────────
# Price move alone overstates a scalp's result. Net results subtract a
# market-in / market-out round trip (Binance USDT-M taker 0.05% per side)
# and add the funding actually paid or received while the trade was open.
ROUND_TRIP_FEE_PCT = 0.10
# How many already-resolved signals the resolver backfills per run with the
# inverse/funding fields added later — bounded so one serverless call can't
# run long.
BACKFILL_BATCH = 40
# A signal that resolved while Binance returned no candles is re-evaluated
# by that backfill for this many days before its no_data outcome is final.
NO_DATA_RETRY_DAYS = 3

# ── Risk parameters ───────────────────────────────
MAX_RISK_SCORE = 85  # max risk score (0-100) before warning
SUGGESTED_HOLD_MIN = 15  # default suggested hold time (minutes)
SUGGESTED_HOLD_MAX = 60  # max hold time suggestion
# chart_analysis caps the TP at the nearest resistance/support, which can
# leave the target closer than the stop (3 of 26 posted trades had R:R < 1,
# down to 0.42). Setups below this reward:risk are not confirmed.
MIN_RR_RATIO = 1.5

# ── Notification cadence ──────────────────────────
# The scan runs every 15 min (.github/workflows/scan.yml) but a "no signals"
# result posts a fresh notification every tick, which reads as spam once the
# 1h-funding bucket is small (often 2-4 symbols) and empty scans are common.
# There's no DB / persisted state between invocations to count ticks, so this
# is a clock-based proxy for "once an hour": true only during the first
# EMPTY_SCAN_HEARTBEAT_WINDOW_MIN minutes of each hour. Keep this <= the
# cron's interval above, or you'll get more than one heartbeat per hour.
# Set to 60 to restore "post every scan, even when empty".
EMPTY_SCAN_HEARTBEAT_WINDOW_MIN = 15
