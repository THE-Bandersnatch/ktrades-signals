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

CREATE INDEX IF NOT EXISTS idx_signals_pending ON signals (resolve_at) WHERE NOT resolved;
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals (symbol);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals (created_at);
