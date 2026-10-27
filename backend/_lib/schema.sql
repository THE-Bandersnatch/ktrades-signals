-- KTRADES Signals track record.
--
-- Run manually against DATABASE_URL_UNPOOLED (direct connection, not the
-- pooled one) when setting up or resetting the database — this is DDL, not
-- application query traffic. Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    entry_price NUMERIC NOT NULL,
    funding_rate_raw NUMERIC NOT NULL,
    funding_rate_hourly NUMERIC NOT NULL,
    funding_interval_h INTEGER NOT NULL,
    persistence_ratio NUMERIC NOT NULL,
    payments_catchable INTEGER NOT NULL,
    est_total_funding_earn NUMERIC NOT NULL,
    risk_score INTEGER NOT NULL,
    hold_min INTEGER NOT NULL,

    -- chart_analyzed distinguishes "ranked outside the top 3, never analyzed"
    -- from "analyzed and rejected" (chart_confirmed=false in both cases) —
    -- conflating those would corrupt the confirmed-vs-not comparison.
    chart_analyzed BOOLEAN NOT NULL DEFAULT false,
    chart_confirmed BOOLEAN NOT NULL,
    chart_confidence INTEGER,
    tp NUMERIC,
    sl NUMERIC,
    rr_ratio NUMERIC,

    -- created_at + hold_min, precomputed so the resolver's query stays a
    -- plain index scan instead of doing interval math on every poll.
    resolve_at TIMESTAMPTZ NOT NULL,
    resolved BOOLEAN NOT NULL DEFAULT false,
    resolved_at TIMESTAMPTZ,
    outcome TEXT,                -- tp_hit | sl_hit | expired_favorable | expired_unfavorable | expired_flat | no_data
    exit_price NUMERIC,
    realized_price_pct NUMERIC   -- signed: positive = price moved in the signal's favor
);

-- Idempotent add for a table created before this column existed.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS chart_analyzed BOOLEAN NOT NULL DEFAULT false;

-- Net-of-costs and inverse ("do the opposite") tracking. The inverse is
-- simulated as its own trade — opposite direction, TP and SL swapped — and
-- walked through the same candles with the same SL-first rule, so a candle
-- touching both levels counts against whichever side is being measured.
-- funding_pct is what the signal's own side was paid (+) or charged (-);
-- the inverse side gets the opposite sign over its own holding window.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS funding_pct NUMERIC;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS net_pct NUMERIC;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS inv_outcome TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS inv_exit_price NUMERIC;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS inv_realized_price_pct NUMERIC;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS inv_funding_pct NUMERIC;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS inv_net_pct NUMERIC;

CREATE INDEX IF NOT EXISTS idx_signals_backfill ON signals (id) WHERE resolved AND net_pct IS NULL AND outcome <> 'no_data';

CREATE INDEX IF NOT EXISTS idx_signals_pending ON signals (resolve_at) WHERE NOT resolved;
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals (symbol);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals (created_at);

-- Strategy version (see config.STRATEGY_VERSION) so rule changes can be
-- compared instead of blended; market context captured at signal time
-- (Binance only serves ~30 days of OI / long-short history); and whether a
-- trade's result has been posted to the channel yet.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS strategy_version TEXT NOT NULL DEFAULT '1';
ALTER TABLE signals ADD COLUMN IF NOT EXISTS features JSONB;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS announced BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_signals_open_symbol ON signals (symbol) WHERE NOT resolved;

-- At most one open signal per coin, enforced by the database: two scans that
-- overlap (the cron and a manual /scan) can otherwise both find a coin free
-- and log it twice. log_signal inserts with ON CONFLICT DO NOTHING and the
-- pipeline posts only what it logged. If this fails on existing duplicates,
-- re-run it once those have resolved (at most PERSISTENCE_MAX_HOLD_MIN).
CREATE UNIQUE INDEX IF NOT EXISTS uniq_signals_open_symbol ON signals (symbol) WHERE NOT resolved;

-- One row per scan, including empty ones, so the site can show when the
-- scanner last ran and what's on the radar between trades.
CREATE TABLE IF NOT EXISTS scans (
    id BIGSERIAL PRIMARY KEY,
    ran_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    api_ok BOOLEAN NOT NULL,
    scanned_symbols INTEGER NOT NULL,
    signals INTEGER NOT NULL,
    confirmed INTEGER NOT NULL,
    radar JSONB NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_scans_ran_at ON scans (ran_at DESC);
