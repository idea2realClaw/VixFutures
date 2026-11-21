#!/usr/bin/env python3
"""VIX Futures Curve - zero-dependency local data server.

Sources:
  - current VX monthly settlements: CBOE futures API
  - historical VX settlements: volchart.io /ajax_historical
  - VIX spot: Yahoo Finance v8 chart, falling back to CNBC / CBOE daily CSV
  - trading-day calendar: CBOE VIX_History.csv

No third-party packages are required.
"""

import argparse
import json
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

CBOE_URL = "https://www-api.cboe.com/us/futures/api/data/?symbol=VX"
SQUAWK_URL = "https://api.squawkflow.com/api/public/vix-term-structure"
VOLCHART_HISTORY_URL = "https://volchart.io/ajax_historical?n1={}"
VIX_HISTORY_CSV = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
YAHOO_SPOT_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=5d&interval=1d"
YAHOO_HISTORY_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?period1={}&period2={}&interval=1d"
CNBC_SPOT_URL = (
    "https://quote.cnbc.com/quote-html-webservice/quote.htm"
    "?symbols=.VIX&requestMethod=quick&noform=1&partnerId=2&fund=1&exthrs=1&output=json"
)

MONTHLY_SYMBOL_RE = re.compile(r"^VX/([FGHJKMNQUVXZ])(\d)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
               7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
MAX_CONTRACTS = 9
MAX_HISTORY_DAYS = 20
CACHE_TTL_SECONDS = 60
DATES_CACHE_TTL_SECONDS = 3600
FETCH_TIMEOUT_SECONDS = 15

_cache_lock = threading.RLock()
_payload_cache = {}
_dates_cache = {"dates": None, "timestamp": 0.0}


def fetch_text(url, headers=None, timeout=FETCH_TIMEOUT_SECONDS):
    request_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; VixFutures/1.0)",
        "Accept": "application/json, text/csv, */*",
    }
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_json(url, headers=None, timeout=FETCH_TIMEOUT_SECONDS):
    return json.loads(fetch_text(url, headers=headers, timeout=timeout))


def iso_from_epoch(epoch):
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def round_or_none(value, digits=4):
    return None if value is None else round(value, digits)


def third_wednesday(year, month):
    """Final settlement day for a VX monthly contract is the third Wednesday."""
    first = date(year, month, 1)
    offset = (2 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def parse_contracts(cboe_payload):
    """Keep monthly VX contracts, sort by expiry, derive per-contract metrics."""
    contracts = []
    for row in cboe_payload.get("data", []):
        symbol = str(row.get("symbol") or "").strip().upper()
        if not MONTHLY_SYMBOL_RE.match(symbol):
            continue

        settlement = float(row.get("settlement") or 0.0)
        if settlement <= 0:
            continue

        expiry = datetime.strptime(row["expiration"], "%m/%d/%Y").date()
        previous = float(row.get("prev_settlement") or 0.0)
        change = settlement - previous if previous > 0 else None

        contracts.append({
            "symbol": symbol,
            "expiration": expiry.isoformat(),
            "settlement": round(settlement, 4),
            "previousSettlement": round(previous, 4) if previous > 0 else None,
            "lastPrice": round(float(row.get("last_price") or 0.0), 4),
            "change": round_or_none(change),
            "changePct": round_or_none(change / previous * 100.0) if change is not None and previous > 0 else None,
            "volume": int(row.get("volume") or 0),
            "openInterest": int(row.get("current_open_int") or row.get("prev_open_int") or 0),
        })

    contracts.sort(key=lambda item: item["expiration"])
    contracts = contracts[:MAX_CONTRACTS]

    for index, contract in enumerate(contracts, start=1):
        contract["month"] = index
        contract["label"] = "M{}".format(index)
        expiry = datetime.strptime(contract["expiration"], "%Y-%m-%d").date()
        contract["monthLabel"] = expiry.strftime("%b %Y")
        contract["shortLabel"] = expiry.strftime("%b %y")

    return contracts


def parse_historical_contracts(target_date):
    """volchart.io returns [startMonth, price1, price2, ...]."""
    headers = {"Referer": "https://volchart.io/", "X-Requested-With": "XMLHttpRequest"}
    raw = fetch_text(VOLCHART_HISTORY_URL.format(target_date), headers=headers, timeout=20)
    values = json.loads(raw)
    if not isinstance(values, list) or len(values) < 2:
        raise ValueError("historical curve unavailable for {}".format(target_date))

    start_month = int(values[0])
    prices = [float(item) for item in values[1:] if item not in (None, "") and float(item) > 0]
    if not prices:
        raise ValueError("historical curve has no prices for {}".format(target_date))

    requested = datetime.strptime(target_date, "%Y-%m-%d").date()
    base_year = requested.year
    if start_month < requested.month - 1:
        base_year += 1

    contracts = []
    for index, price in enumerate(prices, start=1):
        month_index = start_month - 1 + index
        year = base_year + (month_index - 1) // 12
        month = (month_index - 1) % 12 + 1
        contracts.append({
            "symbol": "VX/{}{}".format(MONTH_CODES[month], year % 10),
            "expiration": third_wednesday(year, month).isoformat(),
            "settlement": round(price, 4),
            "previousSettlement": None,
            "lastPrice": None,
            "change": None,
            "changePct": None,
            "volume": None,
            "openInterest": None,
            "month": index,
            "label": "M{}".format(index),
            "monthLabel": date(year, month, 1).strftime("%b %Y"),
            "shortLabel": date(year, month, 1).strftime("%b %y"),
        })

    return contracts[:MAX_CONTRACTS]


def build_pairs(contracts):
    pairs = []
    for left, right in zip(contracts, contracts[1:]):
        diff = right["settlement"] - left["settlement"]
        pct = diff / left["settlement"] * 100.0 if left["settlement"] > 0 else None
        pairs.append({
            "from": left["label"],
            "to": right["label"],
            "difference": round(diff, 4),
            "percent": round(pct, 4) if pct is not None else None,
        })
    return pairs


def build_metrics(contracts):
    front = contracts[0]["settlement"]
    second = contracts[1]["settlement"] if len(contracts) > 1 else None
    back = contracts[-1]["settlement"]

    if back > front:
        regime = "contango"
    elif back < front:
        regime = "backwardation"
    else:
        regime = "flat"

    return {
        "regime": regime,
        "front": front,
        "second": second,
        "back": back,
        "frontSecondSpreadPct": round((second / front - 1.0) * 100.0, 4) if second is not None else None,
        "frontBackSpread": round(back - front, 4),
        "frontBackSpreadPct": round((back / front - 1.0) * 100.0, 4),
        "contractCount": len(contracts),
    }


def cross_check(contracts):
    """Compare CBOE settlements against the independent SquawkFlow feed."""
    try:
        squawk = fetch_json(SQUAWK_URL)
        remote = {
            str(item.get("symbol") or "").strip().upper(): float(item.get("price") or 0.0)
            for item in squawk.get("data", {}).get("contracts", [])
        }
        comparisons = []
        for contract in contracts:
            remote_price = remote.get(contract["symbol"])
            if not remote_price:
                continue
            comparisons.append({
                "symbol": contract["symbol"],
                "cboe": contract["settlement"],
                "other": round(remote_price, 4),
                "absDiff": round(abs(contract["settlement"] - remote_price), 4),
            })
        return {
            "status": "ok" if comparisons else "no_overlap",
            "source": SQUAWK_URL,
            "asOfDate": squawk.get("data", {}).get("asOfDate"),
            "comparisons": comparisons,
            "maxAbsDiff": max((item["absDiff"] for item in comparisons), default=None),
        }
    except (URLError, OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "unavailable", "source": SQUAWK_URL, "error": str(exc)}


def fetch_trading_dates():
    """Recent trading days from the official CBOE daily VIX history CSV."""
    with _cache_lock:
        if _dates_cache["dates"] and time.time() - _dates_cache["timestamp"] < DATES_CACHE_TTL_SECONDS:
            return list(_dates_cache["dates"])

    text = fetch_text(VIX_HISTORY_CSV, timeout=25)
    parsed = []
    for line in text.splitlines()[1:]:
        cell = line.split(",")[0].strip()
        if not cell:
            continue
        try:
            parsed.append(datetime.strptime(cell, "%m/%d/%Y").date())
        except ValueError:
            continue

    today = date.today()
    days = sorted({item for item in parsed if item <= today}, reverse=True)
    if today.weekday() < 5 and (not days or days[0] != today):
        days.insert(0, today)

    result = [item.isoformat() for item in days[:MAX_HISTORY_DAYS + 1]]
    with _cache_lock:
        _dates_cache.update(dates=result, timestamp=time.time())
    return list(result)


def extract_yahoo_spot(payload, target_date):
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return None, None
    result = results[0]
    meta = result.get("meta", {})
    if target_date is None:
        return meta.get("regularMarketPrice"), meta.get("regularMarketTime")

    timestamps = result.get("timestamp") or []
    quotes = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = quotes.get("close") or []
    for stamp, close in zip(timestamps, closes):
        if close is None:
            continue
        if datetime.fromtimestamp(stamp, timezone.utc).date().isoformat() == target_date:
            return close, stamp
    return None, None


def cboe_csv_close(target_date):
    text = fetch_text(VIX_HISTORY_CSV, timeout=25)
    for line in text.splitlines()[1:]:
        cells = line.split(",")
        if len(cells) < 5:
            continue
        try:
            day = datetime.strptime(cells[0].strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        if day.isoformat() == target_date:
            return float(cells[4])
    return None


def fetch_spot(target_date=None):
    """Yahoo v8 chart first, then CNBC / CBOE CSV as documented fallbacks."""
    try:
        if target_date:
            day = datetime.strptime(target_date, "%Y-%m-%d").date()
            start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
            url = YAHOO_HISTORY_URL.format(start, start + 3 * 86400)
        else:
            url = YAHOO_SPOT_URL
        price, stamp = extract_yahoo_spot(fetch_json(url), target_date)
        if price and float(price) > 0:
            return {
                "price": round(float(price), 4),
                "asOf": iso_from_epoch(stamp) if stamp else target_date,
                "source": "Yahoo Finance ^VIX",
                "fallback": False,
                "currentOnly": False,
            }
    except (URLError, OSError, ValueError, KeyError, TypeError, IndexError):
        pass

    if target_date:
        try:
            price = cboe_csv_close(target_date)
            if price and price > 0:
                return {
                    "price": round(price, 4),
                    "asOf": target_date + " (close)",
                    "source": "CBOE VIX daily close",
                    "fallback": True,
                    "currentOnly": False,
                }
        except (URLError, OSError, ValueError, IndexError):
            pass

    try:
        quote = fetch_json(CNBC_SPOT_URL)["QuickQuoteResult"]["QuickQuote"][0]
        price = float(quote["last"])
        if price > 0:
            quote_time = str(quote.get("last_time") or "")
            return {
                "price": round(price, 4),
                "asOf": quote_time or None,
                "source": "CNBC .VIX",
                "fallback": True,
                "currentOnly": bool(target_date and quote_time[:10] != target_date),
            }
    except (URLError, OSError, ValueError, KeyError, TypeError, IndexError):
        pass

    return {
        "price": None,
        "asOf": None,
        "source": None,
        "fallback": True,
        "currentOnly": False,
        "error": "spot unavailable from Yahoo, CBOE CSV and CNBC",
    }


def build_payload(target_date=None, force=False):
    """Build a fresh payload for the requested trading day."""
    cache_key = target_date or "latest"
    with _cache_lock:
        cached = _payload_cache.get(cache_key)
        if not force and cached and time.time() - cached["timestamp"] < CACHE_TTL_SECONDS:
            result = dict(cached["payload"])
            result["cache"] = "hit"
            return result

    is_historical = bool(target_date)
    if is_historical:
        contracts = parse_historical_contracts(target_date)
        source = {
            "primary": "volchart.io historical VX settlements",
            "primaryUrl": VOLCHART_HISTORY_URL.format(target_date),
            "asOfDate": target_date,
            "crossCheck": {"status": "not_applicable", "reason": "historical feed"},
        }
    else:
        cboe_payload = fetch_json(CBOE_URL)
        contracts = parse_contracts(cboe_payload)
        if not contracts:
            raise ValueError("CBOE returned no monthly VX contracts")
        stamp = str(cboe_payload.get("lastUpdate") or "")
        target_date = stamp[:10] if DATE_RE.match(stamp[:10]) else date.today().isoformat()
        source = {
            "primary": "CBOE VX futures settlement (delayed)",
            "primaryUrl": CBOE_URL,
            "cboeLastUpdate": cboe_payload.get("lastUpdate"),
            "asOfDate": target_date,
            "crossCheck": cross_check(contracts),
        }

    payload = {
        "ok": True,
        "date": target_date,
        "isHistorical": is_historical,
        "contracts": contracts,
        "pairs": build_pairs(contracts),
        "metrics": build_metrics(contracts),
        "spot": fetch_spot(target_date if is_historical else None),
        "source": source,
        "fetchedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cache": "miss",
    }
    payload["source"]["fetchedAt"] = payload["fetchedAt"]

    with _cache_lock:
        _payload_cache[cache_key] = {"payload": payload, "timestamp": time.time()}
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "VixFutures/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[{}] {}\n".format(
            datetime.now().astimezone().isoformat(timespec="seconds"), fmt % args))

    def _send(self, status, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False, indent=2), "application/json; charset=utf-8")

    def _serve_file(self, relative_path):
        candidate = (STATIC_DIR / relative_path).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._send_json(403, {"ok": False, "error": "forbidden"})
            return
        if not candidate.is_file():
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        suffix = candidate.suffix.lower()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
        }.get(suffix, "application/octet-stream")
        self._send(200, candidate.read_bytes(), content_type)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        force = "refresh=1" in parsed.query

        if path == "/api/curve":
            target_date = params.get("date", [None])[0]
            if target_date and not DATE_RE.match(target_date):
                self._send_json(400, {"ok": False, "error": "date must be YYYY-MM-DD"})
                return
            try:
                self._send_json(200, build_payload(target_date, force=force))
            except (URLError, OSError, ValueError, KeyError, TypeError) as exc:
                self._send_json(502, {"ok": False, "error": "upstream failure: {}".format(exc)})
            return

        if path == "/api/dates":
            try:
                dates = fetch_trading_dates()
                self._send_json(200, {"ok": True, "dates": dates, "count": len(dates)})
            except (URLError, OSError, ValueError) as exc:
                self._send_json(502, {"ok": False, "error": str(exc)})
            return

        if path == "/api/spot":
            target_date = params.get("date", [None])[0]
            self._send_json(200, {"ok": True, "spot": fetch_spot(target_date)})
            return

        if path == "/api/health":
            self._send_json(200, {
                "ok": True,
                "service": "VixFutures",
                "cachedPayloads": len(_payload_cache),
                "datesCached": _dates_cache["dates"] is not None,
            })
            return

        if path in ("/", "/index.html"):
            self._serve_file("index.html")
            return

        if path.startswith("/static/"):
            self._serve_file(path[len("/static/"):])
            return

        self._send_json(404, {"ok": False, "error": "not found"})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve the VIX futures curve from CBOE data.")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="bind port (default: 8765)")
    parser.add_argument("--once", action="store_true", help="fetch once, print JSON and exit")
    parser.add_argument("--json", action="store_true", help="explicit JSON output mode used with --once")
    parser.add_argument("--date", help="target trading day YYYY-MM-DD used with --once")
    args = parser.parse_args(argv)

    if args.once:
        try:
            if args.date and not DATE_RE.match(args.date):
                raise ValueError("date must be YYYY-MM-DD")
            payload = build_payload(args.date, force=True)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        except (URLError, OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("VIX Futures Curve -> http://{}:{}".format(args.host, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
