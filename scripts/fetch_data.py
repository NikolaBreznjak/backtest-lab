#!/usr/bin/env python3
"""Fetch real daily OHLCV bars from Yahoo Finance v8 Chart API.
Never invents or interpolates prices. Fails closed on error.
"""
import csv
import datetime
import json
import math
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PRICES_DIR = DATA_DIR / "prices"

UNIVERSE = [
    {"symbol": "MSFT", "file_key": "MSFT", "name": "Microsoft Corp."},
    {"symbol": "AAPL", "file_key": "AAPL", "name": "Apple Inc."},
    {"symbol": "NVDA", "file_key": "NVDA", "name": "NVIDIA Corp."},
    {"symbol": "^GSPC", "file_key": "GSPC", "name": "S&P 500 Index"},
]

LJUBLJANA_TZ = ZoneInfo("Europe/Ljubljana")


def fetch_symbol(symbol: str) -> tuple[list[dict], dict]:
    hosts = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
    params = {"range": "5y", "interval": "1d", "includeAdjustedClose": "true"}
    headers = {"User-Agent": "Mozilla/5.0"}

    last_exc = None
    payload = None
    for attempt in range(5):
        host = hosts[attempt % len(hosts)]
        url = f"https://{host}/v8/finance/chart/{symbol}"
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=20)
            if resp.status_code == 429:
                wait_s = 2.0 * (attempt + 1)
                print(f"[fetch] 429 rate-limit on {symbol} ({host}), waiting {wait_s:.0f}s...", file=sys.stderr)
                time.sleep(wait_s)
                continue
            resp.raise_for_status()
            payload = resp.json()
            break
        except Exception as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))

    if payload is None:
        raise RuntimeError(f"Failed to fetch {symbol} after retries: {last_exc}")

    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"Yahoo Finance API error for {symbol}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise RuntimeError(f"Empty result for {symbol}")

    res = results[0]
    meta = res.get("meta") or {}
    timestamps = res.get("timestamp") or []
    quote = (res.get("indicators") or {}).get("quote", [{}])[0]
    adj_list = ((res.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    if not timestamps or len(opens) != len(timestamps):
        raise RuntimeError(f"Malformed OHLC arrays for {symbol}")

    exchange_tz_name = meta.get("exchangeTimezoneName") or "America/New_York"
    try:
        exch_tz = ZoneInfo(exchange_tz_name)
    except Exception:
        exch_tz = ZoneInfo("America/New_York")

    bars = []
    seen_dates = set()
    dropped = 0
    for i, ts in enumerate(timestamps):
        o = opens[i]
        h = highs[i]
        l = lows[i]
        c = closes[i]
        v = volumes[i] if i < len(volumes) else 0
        adj = adj_list[i] if i < len(adj_list) else c

        if o is None or h is None or l is None or c is None:
            dropped += 1
            continue
        try:
            o, h, l, c = float(o), float(h), float(l), float(c)
            adj = float(adj) if adj is not None else c
            v = int(v) if v is not None else 0
        except (TypeError, ValueError):
            dropped += 1
            continue

        if any(not math.isfinite(x) or x <= 0 for x in (o, h, l, c)):
            dropped += 1
            continue
        if h < l:
            dropped += 1
            continue

        dt_exch = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).astimezone(exch_tz)
        date_str = dt_exch.strftime("%Y-%m-%d")
        if date_str in seen_dates:
            bars = [b for b in bars if b["date"] != date_str]
        seen_dates.add(date_str)

        bars.append({
            "date": date_str,
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "adj_close": round(adj, 4),
            "volume": v,
        })

    bars.sort(key=lambda b: b["date"])
    if len(bars) < 500:
        raise RuntimeError(f"Insufficient valid bars for {symbol}: got {len(bars)}, require >= 500")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_lj = now_utc.astimezone(LJUBLJANA_TZ)
    meta_out = {
        "symbol": symbol,
        "currency": meta.get("currency", "USD"),
        "exchange": meta.get("exchangeName", ""),
        "timezone": exchange_tz_name,
        "bars": len(bars),
        "dropped_incomplete_bars": dropped,
        "first_date": bars[0]["date"],
        "last_date": bars[-1]["date"],
        "last_close": bars[-1]["close"],
        "fetched_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_ljubljana": now_lj.strftime("%Y-%m-%d %H:%M %Z"),
    }
    return bars, meta_out


def fetch_all() -> dict:
    PRICES_DIR.mkdir(parents=True, exist_ok=True)
    all_bars = {}
    all_meta = {}

    for idx, item in enumerate(UNIVERSE):
        if idx > 0:
            time.sleep(1.0)
        sym = item["symbol"]
        fk = item["file_key"]
        bars, meta = fetch_symbol(sym)
        meta["name"] = item["name"]
        meta["file_key"] = fk

        csv_path = PRICES_DIR / f"{fk}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["date", "open", "high", "low", "close", "adj_close", "volume"]
            )
            writer.writeheader()
            writer.writerows(bars)

        all_bars[sym] = bars
        all_meta[sym] = meta
        print(
            f"[fetch] {sym:6s} -> {len(bars)} bars ({meta['first_date']} .. {meta['last_date']}), "
            f"last close={meta['last_close']}, dropped={meta['dropped_incomplete_bars']}"
        )

    out_json = {
        "source": "Yahoo Finance v8 Chart API (1d, 5y)",
        "universe": [u["symbol"] for u in UNIVERSE],
        "meta": all_meta,
        "bars": all_bars,
    }
    with open(DATA_DIR / "bars.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, separators=(",", ":"))

    return out_json


if __name__ == "__main__":
    try:
        fetch_all()
    except Exception as exc:
        print(f"ERROR: Data fetch aborted: {exc}", file=sys.stderr)
        sys.exit(1)
