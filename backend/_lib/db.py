#!/usr/bin/env python3
"""
db.py — Postgres connection helper for the signal track record.

One short-lived connection per call, closed immediately after — this is a
serverless function invoked at most every few minutes, not a long-running
process that benefits from holding a connection open. Neon's pooled
DATABASE_URL (PgBouncer) is what makes that an acceptable pattern here
instead of exhausting the database's own connection limit.
"""
import psycopg2
import psycopg2.extras

from . import config


def get_conn():
    return psycopg2.connect(config.DATABASE_URL)
