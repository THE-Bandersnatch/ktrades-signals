#!/usr/bin/env python3
"""
risk_checks.py — reasons not to touch a coin, whatever its funding says.

Funding goes extreme for a reason, and the reason is often news. On
2026-10-29 BLUR paid longs 1.49% per 4h and the funding fade read that as a
long, while Blur had announced on 2026-10-12 that its website shuts down on
2026-11-12 and Binance had carried BLUR on its Monitoring Tag (its
delisting watch list) since 2026-06-18. HUMA was posted long 14 times while
down 50-60% over 30 days. Every check here can only veto a trade, never
make one, and none of them is an edge (see config.MAX_ADVERSE_MOVE_PCT).

Sources, all public and keyless:
  - Binance product list (binance.com bapi): the Monitoring Tag, project names
  - Binance futures exchangeInfo: contracts that are winding down
  - Binance announcements, delisting catalog: coins named in delist titles
  - Google News RSS, then Bing News RSS: headlines that name the coin next
    to a red-flag word
The 7- and 30-day moves come from daily_moves(), via scanner.fetch_context_features.

A source that can't be read, or answers with something that doesn't look
like its normal payload, fails the check that depends on it: a trade card
must never claim a check that didn't run. "No red-flag headline" only means
none was found — news coverage of small coins is thin.
"""
import email.utils
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from . import config

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; KTRADESSignals/1.0)"})

PRODUCTS_URL = "https://www.binance.com/bapi/asset/v2/public/asset-service/product/get-products"
CMS_LIST_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
DELIST_CATALOG_ID = 161
GOOGLE_NEWS_URL = "https://news.google.com/rss/search"
BING_NEWS_URL = "https://www.bing.com/news/search"
# exchangeInfo gives a perpetual with no end date a deliveryDate in 2100.
NO_DELIVERY_MS = 4_000_000_000_000
# Sanity floors: Binance lists well over a thousand spot products and
# hundreds of USDT perpetuals. Fewer means a truncated or wrong payload.
MIN_PRODUCTS = 300
MIN_PERPETUALS = 100

# Words that, in a headline naming the coin, mean something is wrong with
# the project or its market rather than ordinary price talk.
RED_FLAGS = re.compile(
    r"\bshut(?:s|ting)?[\s-]?down\b|\bshutdown\b|\bsunset(?:s|ting)?\b|\bdeprecat\w*|"
    r"\bwind(?:s|ing)?[\s-]down\b|\bdiscontinu\w*|\bclosure\b|\bdelist\w*|"
    r"\bhack(?:s|ed|er|ers)?\b|\bexploit(?:s|ed)?\b|\bdrain(?:s|ed)?\b|\bstolen\b|\btheft\b|"
    r"\brug(?:s|ged|[\s-]?pull)?\b|\binsolven\w*|\bbankrupt\w*|\blawsuits?\b|\bsue[sd]?\b|"
    r"\bfraud\w*|\bscam\w*|\barrest(?:s|ed)?\b|\bhalt(?:s|ed)?\b|\bsuspen(?:d|ds|ded|sion)\b|"
    r"\bfr(?:eeze|eezes|ozen)\b|\bvulnerab\w*|\bflaws?\b|\battack(?:s|ed|er|ers)?\b|"
    r"\bunlock(?:s|ed|ing)?\b|\bcrash(?:es|ed|ing)?\b|\bplung(?:e|es|ed|ing)\b|"
    r"\bcollaps(?:e|es|ed|ing)\b|\bdump(?:s|ed|ing)?\b|\brecord low\b|\ball[\s-]time low\b",
    re.I,
)


def _get_json(url: str, params: dict = None, timeout: int = 8):
    r = SESSION.get(url, params=params, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.json()


def _asset_key(base: str, known: set) -> str:
    """The name a futures base goes by in Binance's spot product list: itself
    when listed (1000CAT is), else the bare asset of a 1000-/1000000-/1M-
    prefixed contract (1000PEPE -> PEPE), else itself."""
    if base in known:
        return base
    for prefix in ("1000000", "1000", "1M"):
        if base.startswith(prefix) and base[len(prefix):] in known:
            return base[len(prefix):]
    return base


def load_context() -> dict:
    """Everything the per-coin checks need, fetched once per scan. A source
    that fails lands in errors, and every check that depends on it fails."""
    ctx = {"products": set(), "monitoring": set(), "names": {}, "delisting": {}, "errors": {}}

    try:
        products = _get_json(PRODUCTS_URL, {"includeEtf": "true"})["data"] or []
        if len(products) < MIN_PRODUCTS:
            raise RuntimeError(f"only {len(products)} products")
        for p in products:
            base = p.get("b")
            if not base:
                continue
            ctx["products"].add(base)
            if p.get("an"):
                ctx["names"].setdefault(base, p["an"])
            if any(str(t).lower() == "monitoring" for t in (p.get("tags") or [])):
                ctx["monitoring"].add(base)
    except Exception as e:
        ctx["errors"]["tags"] = f"Binance product list: {type(e).__name__} {e}"[:160]

    futures_bases = set()
    bare_to_contracts = {}  # PEPE -> {"1000PEPE"}: notices name the asset, not the contract
    try:
        info = _get_json(f"{config.BASE_URL}/fapi/v1/exchangeInfo", timeout=10)
        for s in info.get("symbols") or []:
            if s.get("contractType") != "PERPETUAL" or s.get("quoteAsset") != "USDT":
                continue
            base = s["baseAsset"]
            futures_bases.add(base)
            for prefix in ("1000000", "1000", "1M"):
                if base.startswith(prefix) and len(base) > len(prefix) + 1:
                    bare_to_contracts.setdefault(base[len(prefix):], set()).add(base)
            if s.get("status") != "TRADING":
                ctx["delisting"][base] = f"Binance contract status {s.get('status')}"
            elif int(s.get("deliveryDate") or NO_DELIVERY_MS) < NO_DELIVERY_MS:
                day = datetime.fromtimestamp(int(s["deliveryDate"]) / 1000, timezone.utc).strftime("%Y-%m-%d")
                ctx["delisting"][base] = f"Binance futures delisting on {day}"
        if len(futures_bases) < MIN_PERPETUALS:
            raise RuntimeError(f"only {len(futures_bases)} USDT perpetuals")
    except Exception as e:
        ctx["errors"]["delist"] = f"Binance exchangeInfo: {type(e).__name__} {e}"[:160]

    try:
        data = _get_json(CMS_LIST_URL, {"type": 1, "catalogId": DELIST_CATALOG_ID, "pageNo": 1, "pageSize": 50})
        articles = [a for c in data["data"]["catalogs"] for a in c["articles"]]
        if not articles:
            raise RuntimeError("no articles")
        cutoff_ms = (time.time() - config.DELIST_LOOKBACK_DAYS * 86400) * 1000
        for a in articles:
            title = a.get("title") or ""
            if a.get("releaseDate", 0) < cutoff_ms or not re.search(r"\b(delist|remov)", title, re.I):
                continue
            day = datetime.fromtimestamp(a["releaseDate"] / 1000, timezone.utc).strftime("%Y-%m-%d")
            # Titles name coins as BLUR, BLURUSDT or, for a 1000-prefixed
            # contract, its bare asset (PEPE for 1000PEPE). Only words that map
            # to a real futures contract count, so "USDⓈ-M" or "ALPHA" never match.
            for word in re.findall(r"\b[A-Z0-9]{2,15}\b", title):
                base = word[:-4] if word.endswith("USDT") else word
                targets = ({base} if base in futures_bases else set()) | bare_to_contracts.get(base, set())
                for contract in targets:
                    ctx["delisting"].setdefault(contract, f"Binance delisting notice {day}")
    except Exception as e:
        ctx["errors"].setdefault("delist", f"Binance announcements: {type(e).__name__} {e}"[:160])

    return ctx


def assess(signal: dict, ctx: dict) -> list:
    """The checks that need no news lookup, as (passed, text) pairs in a
    fixed order: Binance flags, then the 7- and 30-day moves."""
    base = signal["symbol"]
    key = _asset_key(base, ctx["products"])
    long = signal["direction"] == "LONG"
    checks = []

    failed_sources = [ctx["errors"][k] for k in ("tags", "delist") if k in ctx["errors"]]
    if failed_sources:
        checks.append((False, "Binance flag check unavailable (" + "; ".join(failed_sources) + ")"))
    else:
        problems = []
        if key in ctx["monitoring"]:
            problems.append("Binance Monitoring Tag (delisting watch list)")
        if base in ctx["delisting"]:
            problems.append(ctx["delisting"][base])
        checks.append((not problems, "; ".join(problems) if problems
                       else "No Binance Monitoring Tag or delisting notice"))

    feats = signal.get("features") or {}
    mom7, mom30 = feats.get("mom_7d_pct"), feats.get("mom_30d_pct")
    days = feats.get("mom_hist_days") or 30
    limit = config.MAX_ADVERSE_MOVE_PCT
    if mom7 is None or mom30 is None:
        checks.append((False, "7/30-day move unavailable (price history too short or not loaded)"))
    else:
        # Positive = price moved against the trade: down for a long, up for a short.
        against = max(-mom7, -mom30) if long else max(mom7, mom30)
        rule = f"a long needs both above -{limit:.0f}%" if long else f"a short needs both below +{limit:.0f}%"
        label30 = "30-day" if days >= 30 else f"{days}-day (since listing)"
        checks.append((against < limit, f"7-day {mom7:+.1f}%, {label30} {mom30:+.1f}% ({rule})"))
    return checks


DAY_MS = 86_400_000


def daily_moves(klines: list, now_ms: int = None) -> dict:
    """7- and 30-day moves from Binance daily klines (oldest first, the last
    one still forming, so its close is the live price). Each compares the
    live price with the close of the last daily candle that closed at least
    7 / 30 days ago, so a window is 7-8 / 30-31 days and never short — the
    same reference the backtest in config.MAX_ADVERSE_MOVE_PCT used. A coin
    with under 30 days of candles is measured from its first close
    (mom_hist_days says how far back); under 7 days gives nothing, and
    assess() then fails the check. Fetch at least 32 candles."""
    if not isinstance(klines, list) or len(klines) < 2:
        return {}
    now_ms = now_ms or int(time.time() * 1000)
    price = float(klines[-1][4])
    closed = [(int(k[0]) + DAY_MS, float(k[4])) for k in klines[:-1]]

    def close_before(days):
        older = [c for t, c in closed if t <= now_ms - days * DAY_MS]
        return older[-1] if older else None

    ref7, ref30, hist_days = close_before(7), close_before(30), 30
    if ref7 is None:
        return {}
    if ref30 is None:
        ref30 = closed[0][1]
        hist_days = int((now_ms - closed[0][0]) // DAY_MS) + 1
    return {"mom_7d_pct": round((price / ref7 - 1) * 100, 3),
            "mom_30d_pct": round((price / ref30 - 1) * 100, 3),
            "mom_hist_days": hist_days}


def _parse_rss(content: bytes) -> list:
    """(published datetime or None, title) for every item in an RSS feed.
    Raises on anything that isn't RSS, such as a consent or captcha page."""
    root = ET.fromstring(content)
    if root.find("channel") is None:
        raise ValueError("not an RSS feed")
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        published = None
        try:
            published = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "")
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
        items.append((published, title))
    return items


def _names_coin(title: str, name: str, ticker: str) -> bool:
    """Whether a headline is about this coin: its project name (any case) or
    its ticker (exact case, so HOT isn't "hot", and only 3+ letters)."""
    if name and re.search(rf"(?<![\w$]){re.escape(name)}(?!\w)", title, re.I):
        return True
    return len(ticker) >= 3 and re.search(rf"(?<![\w$]){re.escape(ticker)}(?!\w)", title) is not None


def news_check(symbol: str, ctx: dict) -> tuple:
    """(passed, text): fails on a headline from the last NEWS_LOOKBACK_DAYS
    that names the coin next to a red-flag word, when no news feed answers,
    or when the coin has neither a known project name nor a ticker of 3+
    letters to search for."""
    key = _asset_key(symbol, ctx["products"])
    name = ctx["names"].get(key)
    if name:
        # Binance writes some names as "1000*Simons Cat".
        name = re.sub(r"^\d+\*?\s*", "", name).strip() or None
    ticker = key
    if not name and len(ticker) < 3:
        return False, f"News check impossible: ticker {ticker} is too ambiguous to search"

    days = config.NEWS_LOOKBACK_DAYS
    term = f'"{name}"' if name else f'"{ticker}"'
    feeds = (
        (GOOGLE_NEWS_URL, {"q": f"{term} crypto when:{days}d", "hl": "en-US", "gl": "US", "ceid": "US:en"}),
        (BING_NEWS_URL, {"q": f"{term} crypto", "format": "rss"}),
    )
    cutoff = time.time() - days * 86400
    answered, errors = False, []
    for url, params in feeds:
        try:
            r = SESSION.get(url, params=params, timeout=5)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            items = _parse_rss(r.content)
        except Exception as e:
            errors.append(f"{url.split('/')[2]}: {type(e).__name__} {e}"[:120])
            continue
        answered = True
        for published, title in items:
            # An undated headline can't be placed inside the window; counting
            # it would let one old article veto a coin forever.
            if published is None or published.timestamp() < cutoff:
                continue
            if _names_coin(title, name, ticker) and RED_FLAGS.search(title):
                return False, f'News {published.strftime("%d %b")}: "{title[:110]}"'
        if items:
            return True, f"No red-flag headline found in {days} days"
    if answered:
        return True, f"No headlines found in {days} days"
    print(f"[Risk] news check failed for {symbol}: {errors}")
    return False, "News check unavailable: no news feed answered"
