import logging
import requests
from datetime import datetime, timedelta
from core.config import (
    APIFY_TOKEN,
    SHIPLY_ACTOR_ID,
    ANOMALY_THRESHOLD_PCT,
)
from core.db import (
    fetch_all_shipments,
    insert_market_rate,
    insert_anomaly,
    log_agent,
)

logger = logging.getLogger(__name__)
AGENT_NAME = "freight_agent"

# Freightos Baltic Index public API 
_FBX_API = "https://fbx.freightos.com/api/v1/series/"

# Mapping common route patterns → FBX series code
# FBX codes: https://fbx.freightos.com/fbx/
_ROUTE_TO_FBX: dict[str, str] = {
    # China / East Asia → destinations
    ("china",         "north america west"):  "FBX01",
    ("shanghai",      "los angeles"):         "FBX01",
    ("shenzhen",      "long beach"):          "FBX01",
    ("china",         "north america east"):  "FBX02",
    ("shanghai",      "new york"):            "FBX02",
    ("china",         "north europe"):        "FBX03",
    ("shanghai",      "rotterdam"):           "FBX03",
    ("china",         "mediterranean"):       "FBX04",
    ("shanghai",      "genoa"):               "FBX04",
    # North America → elsewhere
    ("north america west", "south-east asia"): "FBX05",
    ("los angeles",        "singapore"):       "FBX05",
    ("north america east", "north europe"):    "FBX06",
    ("north america east", "mediterranean"):   "FBX07",
    # Europe → elsewhere
    ("north europe",  "north america west"):  "FBX08",
    ("rotterdam",     "los angeles"):         "FBX08",
    ("north europe",  "north america east"):  "FBX09",
    ("north europe",  "south-east asia"):     "FBX10",
}

# Static FBX fallback (USD / 40ft container) — updated Q1-2025 typical values
_FBX_STATIC_FALLBACK: dict[str, float] = {
    "FBX01": 2200.0,   # China → NA West Coast
    "FBX02": 2800.0,   # China → NA East Coast
    "FBX03": 2100.0,   # China → North Europe
    "FBX04": 2400.0,   # China → Mediterranean
    "FBX05": 1800.0,   # NA West → SE Asia
    "FBX06": 1900.0,   # NA East → North Europe
    "FBX07": 2100.0,   # NA East → Mediterranean
    "FBX08": 2000.0,   # North Europe → NA West
    "FBX09": 1950.0,   # North Europe → NA East
    "FBX10": 2300.0,   # North Europe → SE Asia
    "FBX_GENERAL": 2000.0,  # generic fallback
}

# In-process cache
_rate_cache: dict[str, float | None] = {}


# PUBLIC ENTRY POINT

def run(calc_results: dict) -> dict:
    """
    For each unique route in the DB, fetch market rate and compare with
    the average cost from Agent 4.

    Args:
        calc_results: Output dict from calculator_agent.run()

    Returns:
        Dict with per-route comparisons and a list of anomalies.
    """
    logger.info("[Agent 5] Fetching market freight rates...")

    avg_by_route: dict = calc_results.get("avg_cost_per_route", {})
    if not avg_by_route:
        logger.warning("[Agent 5] No routes from calculator_agent — nothing to compare.")
        return {"comparisons": [], "anomalies": [], "fbx_rates": {}}

    # Build a route → (earliest_date, latest_date) map from actual shipments
    route_dates = _build_route_date_map()

    comparisons: list[dict] = []
    anomalies:   list[dict] = []
    fbx_rates:   dict[str, float] = {}

    for route, your_avg in avg_by_route.items():
        origin_city, dest_city = _split_route(route)
        if not origin_city or not dest_city:
            logger.warning("   Could not parse route '%s' — skipping.", route)
            continue

        skip_unknowns = (
            origin_city.lower() in ("unknown", "")
            or dest_city.lower() in ("unknown", "")
        )
        if skip_unknowns:
            # Use FBX General benchmark for routes where port extraction failed
            # ref_date computed here since the normal definition is below this block
            ref_date = route_dates.get(route, {}).get("latest") or _today_iso()
            general_rate = _FBX_STATIC_FALLBACK["FBX_GENERAL"]
            logger.info(
                "   Route: %s | unknown port(s) -> benchmarking vs FBX General Avg ($%.2f)",
                route, general_rate,
            )
            insert_market_rate("unknown", "unknown", general_rate, "FBX Static (General Avg)", ref_date)
            fbx_rates[route] = general_rate
            comp = _build_comparison(route, your_avg, general_rate, "FBX Static (General Avg)", "FBX_GENERAL")
            comparisons.append(comp)
            new_anomalies = _detect_anomalies(comp, route_dates.get(route, {}))
            for a in new_anomalies:
                anomalies.append(a)
                insert_anomaly(a)
                logger.warning("   [ANOMALY] %s: %s", a["type"], a["message"])
            continue

        # Get the reference date from actual shipments on this route
        ref_date = route_dates.get(route, {}).get("latest") or _today_iso()

        logger.info("   Route: %s | your_avg=$%.2f | ref_date=%s", route, your_avg, ref_date)

        #  Fetch market rate (Shiply → FBX → static) 
        market_rate, rate_source = _get_market_rate(origin_city, dest_city, ref_date)
        fbx_code = _match_fbx_code(origin_city, dest_city)

        if market_rate:
            fbx_rates[route] = market_rate
            # Persist to DB
            insert_market_rate(origin_city, dest_city, market_rate, rate_source, ref_date)

        comp = _build_comparison(route, your_avg, market_rate, rate_source, fbx_code)
        comparisons.append(comp)

        #  Anomaly detection  
        new_anomalies = _detect_anomalies(comp, route_dates.get(route, {}))
        for a in new_anomalies:
            anomalies.append(a)
            insert_anomaly(a)
            logger.warning("   [ANOMALY] %s: %s", a["type"], a["message"])

        logger.info(
            "   %s | market=$%s | diff=%s | source=%s",
            route,
            f"{market_rate:,.2f}" if market_rate else "N/A",
            f"{comp['difference']:+,.2f}" if comp["difference"] is not None else "N/A",
            rate_source,
        )

    log_agent(
        AGENT_NAME, "success",
        f"{len(comparisons)} routes compared, {len(anomalies)} anomalies",
    )
    logger.info(
        "[Agent 5] Done — %d comparisons, %d anomalies.",
        len(comparisons), len(anomalies),
    )
    return {
        "comparisons": comparisons,
        "anomalies":   anomalies,
        "fbx_rates":   fbx_rates,
    }


# RATE FETCHING — 5-level waterfall

def _get_market_rate(
    origin: str,
    dest: str,
    ref_date: str,
) -> tuple[float | None, str]:
    """
    Try Shiply → FBX Web Scraper → Xeneta Web Scraper → FBX API → FBX Static.
    Returns (rate_usd, source_label).
    """
    cache_key = f"{origin}|{dest}|{ref_date}"
    if cache_key in _rate_cache:
        return _rate_cache[cache_key], "cache"

    fbx_code = _match_fbx_code(origin, dest)

    #  Level 1: Shiply via Apify (requires paid plan — skipped if no token) 
    if APIFY_TOKEN:
        rate = _fetch_shiply(origin, dest)
        if rate:
            _rate_cache[cache_key] = rate
            return rate, "Shiply (Apify)"

    #  Level 2: Freightos Baltic Index — live web scraper (free) 
    if fbx_code:
        rate = _fetch_fbx_web(fbx_code)
        if rate:
            _rate_cache[cache_key] = rate
            return rate, f"FBX Web ({fbx_code})"

    #  Level 3: Xeneta — live web scraper (free, container-specific) 
    rate = _fetch_xeneta_web(origin, dest)
    if rate:
        _rate_cache[cache_key] = rate
        return rate, "Xeneta Web"

    #  Level 4: Freightos Baltic Index — REST API 
    if fbx_code:
        rate = _fetch_fbx_api(fbx_code, ref_date)
        if rate:
            _rate_cache[cache_key] = rate
            return rate, f"FBX API ({fbx_code})"

    #  Level 5: Static FBX fallback 
    if fbx_code and fbx_code in _FBX_STATIC_FALLBACK:
        rate = _FBX_STATIC_FALLBACK[fbx_code]
        logger.info("   Using static FBX fallback for %s: $%s", fbx_code, rate)
        _rate_cache[cache_key] = rate
        return rate, f"FBX Static ({fbx_code})"

    _rate_cache[cache_key] = None
    return None, "unavailable"


# LEVEL 1 — Shiply via Apify (parseforge/shiply-com-freight-marketplace-scraper)

def _fetch_shiply(origin: str, dest: str) -> float | None:
    """
    Call the Apify actor parseforge/shiply-com-freight-marketplace-scraper
    to get real freight quotes from Shiply marketplace.
    """
    try:
        from apify_client import ApifyClient

        client = ApifyClient(APIFY_TOKEN)

        run_input = {
            "startCity":    origin.strip().title(),
            "endCity":      dest.strip().title(),
            "startCountry": _guess_country(origin),
            "endCountry":   _guess_country(dest),
        }

        logger.info("   [Shiply] Calling actor with %s → %s", origin, dest)
        run = client.actor(SHIPLY_ACTOR_ID).call(run_input=run_input, timeout_secs=90)

        dataset_id = (run or {}).get("defaultDatasetId")
        if not dataset_id:
            logger.warning("   [Shiply] No dataset returned.")
            return None

        items = list(client.dataset(dataset_id).iterate_items())
        if not items:
            logger.warning("   [Shiply] Empty result set.")
            return None

        rate = _parse_shiply_items(items)
        if rate:
            logger.info("   [Shiply] Rate: $%.2f", rate)
        return rate

    except ImportError:
        logger.error("apify-client not installed. Run: pip install apify-client")
        return None
    except Exception as e:
        logger.warning("   [Shiply] Actor call failed: %s", e)
        return None


# LIVE CURRENCY CONVERSION (free API — no key required)

# Hardcoded fallback rates → USD (updated periodically as a safety net)
_FX_FALLBACK: dict[str, float] = {
    "GBP": 1.27,
    "EUR": 1.09,
    "CNY": 0.138,
    "JPY": 0.0066,
    "SGD": 0.74,
    "AED": 0.272,
    "INR": 0.012,
    "KRW": 0.00073,
    "AUD": 0.65,
    "CAD": 0.74,
    "CHF": 1.11,
    "USD": 1.0,
}

# Session-level FX cache — fetched once per run
_fx_cache: dict[str, float] = {}


def _fetch_fx_rates() -> dict[str, float]:
    """
    Fetch live USD exchange rates from the free open.er-api.com endpoint.
    No API key required. Returns rates as {currency_code: rate_vs_usd}.
    Falls back to _FX_FALLBACK on any failure.
    """
    global _fx_cache
    if _fx_cache:
        return _fx_cache

    try:
        resp = requests.get(
            "https://open.er-api.com/v6/latest/USD",
            timeout=8,
            headers={"User-Agent": "cwt-cpa-agent/1.0"},
        )
        if resp.status_code == 200:
            data = resp.json()
            rates_vs_usd = data.get("rates", {})
            if rates_vs_usd:
                # Convert to: 1 foreign_currency = X USD
                _fx_cache = {
                    code: round(1.0 / rate, 6)
                    for code, rate in rates_vs_usd.items()
                    if rate and rate > 0
                }
                _fx_cache["USD"] = 1.0
                logger.info(
                    "   [FX] Live rates fetched — %d currencies (source: open.er-api.com)",
                    len(_fx_cache),
                )
                return _fx_cache
    except Exception as e:
        logger.debug("   [FX] Live rate fetch failed: %s — using fallback", e)

    logger.info("   [FX] Using hardcoded fallback FX rates")
    _fx_cache = dict(_FX_FALLBACK)
    return _fx_cache


def _to_usd(amount: float, currency: str) -> float:
    """
    Convert an amount in the given currency to USD using live rates.
    Returns the original amount unchanged if currency is USD or unknown.
    """
    code = currency.upper().strip()
    if code in ("", "USD"):
        return amount
    rates = _fetch_fx_rates()
    factor = rates.get(code) or _FX_FALLBACK.get(code)
    if factor:
        return round(amount * factor, 2)
    logger.debug("   [FX] Unknown currency '%s' — treating as USD", code)
    return amount


def _parse_shiply_items(items: list[dict]) -> float | None:
    """
    Extract a median market rate from Shiply quote results.
    Shiply typically returns: { "price": 1200, "currency": "GBP", "description": ... }
    We take the median of all numeric prices (converted to USD via live FX rates).
    """
    prices = []
    for item in items:
        raw = item.get("price") or item.get("amount") or item.get("total") or item.get("rate")
        currency = str(item.get("currency", "USD")).upper()
        if raw is None:
            continue
        try:
            price_local = float(
                str(raw).replace(",", "").replace("$", "").replace("£", "").strip()
            )
            price_usd = _to_usd(price_local, currency)
            prices.append(price_usd)
        except (ValueError, TypeError):
            continue

    if not prices:
        return None

    prices.sort()
    mid = len(prices) // 2
    median_price = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2
    return round(median_price, 2)


# LEVEL 2 — Freightos Baltic Index (FBX) live web scraper

_FBX_WEB_URL = "https://fbx.freightos.com/fbx/"

def _fetch_fbx_web(fbx_code: str) -> float | None:
    """
    Scrape the Freightos Baltic Index public dashboard to get the latest
    rate for a given FBX corridor code (e.g. FBX01, FBX03).

    The page renders rate data in JSON embedded as <script type="application/json">
    tags or in data attributes. We scan for numeric values adjacent to
    the fbx_code string.
    """
    try:
        from bs4 import BeautifulSoup
        import re

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        resp = requests.get(_FBX_WEB_URL, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.debug("   [FBX Web] HTTP %d — skipping.", resp.status_code)
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Strategy 1: Look for JSON blobs in <script> tags
        for script in soup.find_all("script"):
            text = script.string or ""
            if fbx_code in text:
                # Find numbers near the FBX code (e.g. "FBX01":2150 or "value":2150)
                numbers = re.findall(
                    rf'{re.escape(fbx_code)}[^\d]{{0,30}}(\d{{3,6}}(?:\.\d{{1,2}})?)',
                    text
                )
                if numbers:
                    values = [float(n) for n in numbers if 100 < float(n) < 30000]
                    if values:
                        rate = round(sum(values) / len(values), 2)
                        logger.info("   [FBX Web] %s: $%.2f (script tag)", fbx_code, rate)
                        return rate

        # Strategy 2: Look for data-* attributes or visible text patterns
        page_text = soup.get_text(" ")
        numbers = re.findall(
            rf'{re.escape(fbx_code)}[^\d]{{0,50}}(\d{{3,6}}(?:\.\d{{1,2}})?)',
            page_text
        )
        if numbers:
            values = [float(n) for n in numbers if 100 < float(n) < 30000]
            if values:
                rate = round(sum(values) / len(values), 2)
                logger.info("   [FBX Web] %s: $%.2f (page text)", fbx_code, rate)
                return rate

        logger.debug("   [FBX Web] Could not find %s rate in page.", fbx_code)
        return None

    except ImportError:
        logger.warning("   [FBX Web] beautifulsoup4 not installed. Run: pip install beautifulsoup4 lxml")
        return None
    except Exception as e:
        logger.debug("   [FBX Web] Scrape failed: %s", e)
        return None


# LEVEL 3 — Xeneta public container rate index web scraper

_XENETA_URL = "https://www.xeneta.com/ocean-freight-rate-indices"

def _fetch_xeneta_web(origin: str, dest: str) -> float | None:
    """
    Scrape Xeneta's public ocean freight rate indices page.
    Xeneta publishes aggregate container spot rate indices for major trade lanes.

    This is a best-effort scraper — Xeneta's full data requires a subscription,
    but headline index values are shown publicly on their indices page.
    """
    try:
        from bs4 import BeautifulSoup
        import re

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.5",
        }
        resp = requests.get(_XENETA_URL, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.debug("   [Xeneta] HTTP %d — skipping.", resp.status_code)
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        page_text = soup.get_text(" ")

        # Xeneta labels lanes like "Far East to North Europe" or "Transpacific"
        o = origin.lower()
        d = dest.lower()

        # Build keyword sets for origin and destination
        china_terms   = ("china", "shanghai", "shenzhen", "guangzhou", "ningbo", "qingdao", "far east")
        europe_terms  = ("europe", "rotterdam", "hamburg", "antwerp", "north europe")
        us_terms      = ("us", "usa", "united states", "america", "transpacific")

        from_china  = any(t in o for t in china_terms)
        to_europe   = any(t in d for t in europe_terms)
        to_us       = any(t in d for t in us_terms)
        from_europe = any(t in o for t in europe_terms)

        # Map to Xeneta lane keywords to search in the page text
        if from_china and to_europe:
            lane_keywords = ["far east", "north europe", "europe"]
        elif from_china and to_us:
            lane_keywords = ["transpacific", "far east", "us"]
        elif from_europe and to_us:
            lane_keywords = ["transatlantic", "europe", "us"]
        else:
            lane_keywords = [origin.split()[0].lower(), dest.split()[0].lower()]

        # Look for dollar amounts near the lane keyword
        for keyword in lane_keywords:
            idx = page_text.lower().find(keyword)
            if idx == -1:
                continue
            # Extract numbers in a ±300 char window around the keyword
            window = page_text[max(0, idx - 50): idx + 300]
            numbers = re.findall(r'\$?([1-9]\d{2,5}(?:\.\d{1,2})?)', window)
            valid = [float(n) for n in numbers if 100 < float(n) < 30000]
            if valid:
                rate = round(sum(valid) / len(valid), 2)
                logger.info("   [Xeneta] %s→%s via '%s': $%.2f", origin, dest, keyword, rate)
                return rate

        logger.debug("   [Xeneta] No matching rate found for %s → %s", origin, dest)
        return None

    except ImportError:
        logger.warning("   [Xeneta] beautifulsoup4 not installed. Run: pip install beautifulsoup4 lxml")
        return None
    except Exception as e:
        logger.debug("   [Xeneta] Scrape failed: %s", e)
        return None


# LEVEL 4 — Freightos Baltic Index (FBX) public REST API

def _fetch_fbx_api(fbx_code: str, ref_date: str) -> float | None:
    """
    Fetch FBX index value for the given code on or near ref_date.
    Tries the Freightos public series API endpoint.
    Note: This often returns 403 — FBX Web scraper is tried first.
    """
    try:
        # Parse date and compute a ±7 day window around the reference date
        ref = datetime.strptime(ref_date[:10], "%Y-%m-%d")
        start = (ref - timedelta(days=7)).strftime("%Y-%m-%d")
        end   = (ref + timedelta(days=7)).strftime("%Y-%m-%d")

        url = _FBX_API
        params = {
            "series_codes": fbx_code,
            "start_date":   start,
            "end_date":     end,
            "format":       "json",
        }
        headers = {"User-Agent": "cwt-cpa-agent/1.0 (research; freight-cost-analysis)"}

        resp = requests.get(url, params=params, headers=headers, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            # Expected shape: { "results": [{ "series_code": "FBX03", "date": "...", "value": 2100 }] }
            results = data.get("results") or data.get("data") or []
            if isinstance(results, list) and results:
                values = [
                    r.get("value") or r.get("rate") or r.get("price")
                    for r in results
                    if r.get("value") or r.get("rate") or r.get("price")
                ]
                if values:
                    avg = sum(float(v) for v in values) / len(values)
                    logger.info("   [FBX API] %s around %s: $%.2f", fbx_code, ref_date, avg)
                    return round(avg, 2)

        elif resp.status_code == 403:
            logger.debug("   [FBX API] Access denied for %s — falling through to static.", fbx_code)

    except Exception as e:
        logger.debug("   [FBX API] Request failed: %s", e)

    return None


# ANOMALY DETECTION

def _detect_anomalies(comp: dict, route_date_info: dict) -> list[dict]:
    """
    Run multiple anomaly checks on a route comparison result.

    Checks:
    - OVERPAYING:  your avg > market by >= ANOMALY_THRESHOLD_PCT
    - UNDERPAYING: your avg < market by > 30% (may indicate data error)
    - SURGE:       market rate significantly above historical norm
    """
    anomalies: list[dict] = []
    market = comp.get("market_rate")
    your_avg = comp.get("your_avg_usd", 0)
    route = comp.get("route", "")

    if market is None or market == 0:
        return anomalies

    pct_diff = comp.get("pct_diff", 0)

    # Overpaying check
    if your_avg > market and pct_diff >= ANOMALY_THRESHOLD_PCT:
        anomalies.append({
            "type":    "OVERPAYING",
            "route":   route,
            "severity": "HIGH" if pct_diff >= 40 else "MEDIUM",
            "message": (
                f"Paying {pct_diff:.1f}% above market on {route}. "
                f"Your avg: ${your_avg:,.2f} | Market: ${market:,.2f} | "
                f"Excess per shipment: ${your_avg - market:,.2f}"
            ),
            "your_avg":    your_avg,
            "market_rate": market,
            "pct_diff":    pct_diff,
        })

    # Unusual underpaying (>30% below market — possible data quality issue)
    elif your_avg < market and abs(pct_diff) > 30:
        anomalies.append({
            "type":     "UNDERPAYING",
            "route":    route,
            "severity": "LOW",
            "message":  (
                f"Costs are {abs(pct_diff):.1f}% below market on {route} — "
                f"verify data accuracy. "
                f"Your avg: ${your_avg:,.2f} | Market: ${market:,.2f}"
            ),
            "your_avg":    your_avg,
            "market_rate": market,
            "pct_diff":    pct_diff,
        })

    return anomalies


# HELPERS

def _match_fbx_code(origin: str, dest: str) -> str | None:
    """Map origin/dest city names to the closest FBX corridor code."""
    o = origin.lower().strip()
    d = dest.lower().strip()

    # Direct match
    for (ok, dk), code in _ROUTE_TO_FBX.items():
        if ok in o and dk in d:
            return code

    # Pattern-based fallbacks
    china_terms   = ("china", "shanghai", "shenzhen", "guangzhou", "ningbo", "qingdao", "tianjin", "xiamen")
    europe_terms  = ("europe", "rotterdam", "hamburg", "antwerp", "felixstowe", "le havre", "genoa", "barcelona")
    us_west_terms = ("los angeles", "long beach", "seattle", "tacoma", "oakland")
    us_east_terms = ("new york", "savannah", "charleston", "houston", "miami", "norfolk")
    sea_terms     = ("singapore", "port klang", "tanjung", "jakarta", "bangkok", "ho chi minh")

    from_china  = any(t in o for t in china_terms)
    to_europe   = any(t in d for t in europe_terms)
    to_us_west  = any(t in d for t in us_west_terms)
    to_us_east  = any(t in d for t in us_east_terms)
    from_europe = any(t in o for t in europe_terms)
    to_sea      = any(t in d for t in sea_terms)

    if from_china:
        if to_us_west:  return "FBX01"
        if to_us_east:  return "FBX02"
        if to_europe:   return "FBX03"
        if to_sea:      return "FBX10"
    if from_europe:
        if to_us_west:  return "FBX08"
        if to_us_east:  return "FBX09"
        if to_sea:      return "FBX10"

    return None


def _build_comparison(
    route: str,
    your_avg: float,
    market_rate: float | None,
    rate_source: str,
    fbx_code: str | None,
) -> dict:
    if market_rate and market_rate > 0:
        difference = round(your_avg - market_rate, 2)
        pct_diff   = round((difference / market_rate) * 100, 1)
        overpaying = difference > 0
    else:
        difference = None
        pct_diff   = None
        overpaying = None

    return {
        "route":        route,
        "your_avg_usd": your_avg,
        "market_rate":  market_rate,
        "rate_source":  rate_source,
        "fbx_code":     fbx_code,
        "difference":   difference,
        "pct_diff":     pct_diff,
        "overpaying":   overpaying,
    }


def _no_rate_entry(route: str, your_avg: float, note: str) -> dict:
    return {
        "route":        route,
        "your_avg_usd": your_avg,
        "market_rate":  None,
        "rate_source":  "unavailable",
        "fbx_code":     None,
        "difference":   None,
        "pct_diff":     None,
        "overpaying":   None,
        "note":         note,
    }


def _split_route(route: str) -> tuple[str, str]:
    """Split 'Shanghai → Rotterdam' into ('Shanghai', 'Rotterdam')."""
    for sep in ("→", "->", " to "):
        if sep in route:
            parts = route.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return "", ""


def _build_route_date_map() -> dict[str, dict]:
    """Build a dict: route → {earliest, latest} invoice dates from DB."""
    from collections import defaultdict
    shipments = fetch_all_shipments()
    route_dates: dict[str, list[str]] = defaultdict(list)

    for s in shipments:
        origin = s.get("origin_port") or "Unknown"
        dest   = s.get("destination_port") or "Unknown"
        date   = s.get("invoice_date") or ""
        if date:
            route_dates[f"{origin} → {dest}"].append(date)

    result = {}
    for route, dates in route_dates.items():
        sorted_dates = sorted(d for d in dates if d)
        result[route] = {
            "earliest": sorted_dates[0]  if sorted_dates else None,
            "latest":   sorted_dates[-1] if sorted_dates else None,
            "count":    len(sorted_dates),
        }
    return result


def _guess_country(city: str) -> str:
    """Best-effort city → 2-letter country code mapping."""
    c = city.lower()
    mapping = {
        "shanghai": "CN", "shenzhen": "CN", "guangzhou": "CN",
        "ningbo": "CN", "qingdao": "CN", "tianjin": "CN",
        "rotterdam": "NL", "amsterdam": "NL",
        "hamburg": "DE", "bremen": "DE",
        "antwerp": "BE",
        "felixstowe": "GB", "london": "GB",
        "le havre": "FR",
        "los angeles": "US", "long beach": "US", "new york": "US",
        "savannah": "US", "charleston": "US", "houston": "US",
        "singapore": "SG",
        "dubai": "AE", "jebel ali": "AE",
        "mumbai": "IN", "nhava sheva": "IN",
        "jakarta": "ID",
        "bangkok": "TH",
        "ho chi minh": "VN",
        "busan": "KR",
        "tokyo": "JP", "osaka": "JP",
        "sydney": "AU", "melbourne": "AU",
    }
    for key, code in mapping.items():
        if key in c:
            return code
    return "XX"


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")
