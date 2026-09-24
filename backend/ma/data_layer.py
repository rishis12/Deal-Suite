"""
M&A Modeling Tool - Data Layer
Fetches TWO companies per request (Acquirer and Target) from:
  - SEC EDGAR (primary: all fundamentals, free, no paywall)
  - Twelve Data (secondary: current share price only, server-side key)

Adapted from the AIO LBO data layer (see /reference/backend/sec_edgar_test.py).
The ticker->CIK resolution, rate limiting, XBRL fallback tag lists, and
missing-field flagging conventions carry over from that proven implementation.
New for M&A: Net Income, Diluted EPS, Diluted Shares Outstanding,
Total Assets, Total Liabilities.
"""

import os
import json
import time
import requests
from pathlib import Path
from typing import Optional
from datetime import datetime


# ============================================================================
# CONFIGURATION
# ============================================================================

# Cache directory for SEC data
CACHE_DIR = Path(__file__).parent / ".sec_cache"

# Build-time snapshot of company_tickers.json, baked into the Docker image
# (see Dockerfile). Render's free tier does not persist local disk writes
# across a cold start, so CACHE_DIR is empty on every fresh container; this
# bundled copy lets the very first request after a cold start resolve
# tickers immediately instead of blocking on (and potentially getting
# rate-limited by) a live SEC fetch. It goes stale between deploys — a
# background refresh (see _ensure_background_refresh) keeps it current for
# any instance that stays warm more than 24h.
BUNDLED_TICKERS_FILE = Path(__file__).parent / "data" / "company_tickers_bundled.json"

# SEC rate limit: max 10 requests/second -> sleep 0.11s between requests.
# This limiter is global across ALL SEC calls in the process, so fetching two
# companies in one user action (roughly double the calls of AIO LBO's
# single-company fetch) still cannot exceed ~9 req/sec.
SEC_REQUEST_DELAY = 0.11

_last_sec_request_time = 0.0

# The limiter must hold under concurrent FastAPI threadpool requests —
# without a lock two threads could both read a stale _last_sec_request_time
# and burst past 10 req/sec (flagged during Phase 1 verification as a
# pre-API-phase requirement).
import threading
_sec_rate_lock = threading.Lock()


# ============================================================================
# SEC EDGAR CLIENT (carried over from AIO LBO)
# ============================================================================

def get_sec_user_agent() -> str:
    """
    Build SEC-compliant User-Agent header.
    SEC requires format: "AppName contact@email.com"
    """
    email = os.environ.get("SEC_CONTACT_EMAIL")
    if not email:
        raise ValueError(
            "SEC_CONTACT_EMAIL environment variable not set.\n"
            "SEC requires a contact email in the User-Agent header.\n"
            "Set it with: set SEC_CONTACT_EMAIL=your@email.com (Windows) or\n"
            "export SEC_CONTACT_EMAIL=your@email.com (Unix)"
        )
    return f"MNA-Modeling-Tool {email}"


def _sec_rate_limit():
    """Enforce SEC rate limit (max 10 requests/second), globally and
    thread-safely (the sleep happens inside the lock so concurrent callers
    serialize rather than bursting)."""
    global _last_sec_request_time
    with _sec_rate_lock:
        elapsed = time.time() - _last_sec_request_time
        if elapsed < SEC_REQUEST_DELAY:
            time.sleep(SEC_REQUEST_DELAY - elapsed)
        _last_sec_request_time = time.time()


def fetch_sec_endpoint(url: str, user_agent: str) -> Optional[dict]:
    """Fetch data from an SEC endpoint with rate limiting and error handling."""
    _sec_rate_limit()

    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 404:
            print(f"  ERROR: Resource not found (404) - {url}")
            return None

        if response.status_code == 403:
            print(f"  ERROR: Access forbidden (403) - check User-Agent header")
            return None

        if response.status_code != 200:
            print(f"  ERROR: HTTP {response.status_code} for {url}")
            print(f"  Response: {response.text[:500]}")
            return None

        return response.json()

    except requests.exceptions.Timeout:
        print(f"  ERROR: Request timeout for {url}")
        return None
    except requests.exceptions.ConnectionError:
        print(f"  ERROR: Connection error for {url}")
        return None
    except json.JSONDecodeError:
        print(f"  ERROR: Invalid JSON response from {url}")
        return None
    except Exception as e:
        print(f"  ERROR: Unexpected error: {str(e)}")
        return None


_ticker_mapping_cache: Optional[dict] = None

# The rate-limit message is asserted on by the frontend-facing error path
# (validator.py / api.py) — it must stay a genuinely different message from
# the "ticker not found" case so users don't mistake a backend rate-limit
# for a typo in what they entered.
SEC_RATE_LIMIT_MESSAGE = (
    "SEC EDGAR is temporarily rate-limiting requests, please try again in a moment"
)


class SECMappingUnavailableError(Exception):
    """
    Raised when company_tickers.json itself could not be obtained (fetch
    failed) AND no cached or bundled copy exists to fall back on.

    This is deliberately a distinct exception from "ticker not found" —
    resolve_ticker_to_cik() only returns None (the not-found signal) once
    the mapping has actually loaded and the ticker genuinely isn't in it.
    """
    pass


def _fetch_company_tickers_raw(user_agent: str) -> dict:
    """
    Fetch company_tickers.json from SEC, with one retry-with-backoff if the
    first attempt is rate-limited (HTTP 429). Raises SECMappingUnavailableError
    on any unrecoverable failure, with a message that distinguishes
    rate-limiting from other failures (network error, unexpected status).
    """
    url = "https://www.sec.gov/files/company_tickers.json"
    headers = {"User-Agent": user_agent, "Accept": "application/json"}

    last_status = None
    last_error = None
    for attempt in range(2):
        _sec_rate_limit()
        try:
            response = requests.get(url, headers=headers, timeout=30)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            if attempt == 0:
                time.sleep(5)
                continue
            raise SECMappingUnavailableError(
                f"Could not reach SEC EDGAR to fetch the ticker mapping: {e}"
            )

        if response.status_code == 200:
            try:
                return response.json()
            except json.JSONDecodeError:
                raise SECMappingUnavailableError(
                    "SEC EDGAR returned an invalid response fetching the ticker mapping."
                )

        last_status = response.status_code
        if response.status_code == 429 and attempt == 0:
            print("  WARNING: SEC rate-limited company_tickers.json fetch (429), retrying in 5s...")
            time.sleep(5)
            continue
        break

    if last_status == 429:
        raise SECMappingUnavailableError(SEC_RATE_LIMIT_MESSAGE)
    if last_status is not None:
        raise SECMappingUnavailableError(
            f"Failed to fetch SEC ticker mapping (HTTP {last_status})."
        )
    raise SECMappingUnavailableError(
        f"Failed to fetch SEC ticker mapping: {last_error}"
    )


_refresh_scheduled = False
_refresh_lock = threading.Lock()


def _ensure_background_refresh(user_agent: str) -> None:
    """
    Start a once-per-process daily background refresh of the on-disk ticker
    mapping. Only relevant for instances that stay warm 24h+ — most Render
    free-tier instances sleep long before that, in which case the bundled
    (build-time) or on-disk copy is simply what's used until the next deploy
    or cold start reseeds it. Never blocks a request.
    """
    global _refresh_scheduled
    with _refresh_lock:
        if _refresh_scheduled:
            return
        _refresh_scheduled = True

        def _refresh():
            try:
                load_ticker_to_cik_mapping(user_agent, force_refresh=True)
            except SECMappingUnavailableError as e:
                print(f"  WARNING: background ticker mapping refresh failed: {e}")
            timer = threading.Timer(24 * 3600, _refresh)
            timer.daemon = True
            timer.start()

        timer = threading.Timer(24 * 3600, _refresh)
        timer.daemon = True
        timer.start()


def load_ticker_to_cik_mapping(user_agent: str, force_refresh: bool = False) -> dict:
    """
    Load the SEC ticker->CIK mapping file.
    Caches in-process and on disk (24h) to avoid repeated downloads.

    Cold start (no disk cache yet): seeds immediately from the bundled
    build-time snapshot rather than fetching live from SEC, so the first
    request after a Render free-tier wake-up never blocks on (or risks
    rate-limiting against) a live fetch.

    Returns dict mapping uppercase ticker -> CIK (as int).
    Raises SECMappingUnavailableError only if a live fetch is attempted,
    fails, and there is no disk cache or bundled copy to fall back on.
    """
    global _ticker_mapping_cache
    if _ticker_mapping_cache is not None and not force_refresh:
        return _ticker_mapping_cache

    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / "company_tickers.json"

    if not force_refresh and not cache_file.exists() and BUNDLED_TICKERS_FILE.exists():
        print("  Using bundled company_tickers.json snapshot (cold start)")
        with open(BUNDLED_TICKERS_FILE, "r") as f:
            raw_data = json.load(f)
        with open(cache_file, "w") as f:
            json.dump(raw_data, f)
        _ticker_mapping_cache = _parse_ticker_mapping(raw_data)
        _ensure_background_refresh(user_agent)
        return _ticker_mapping_cache

    if not force_refresh and cache_file.exists():
        file_age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if file_age_hours < 24:
            with open(cache_file, "r") as f:
                raw_data = json.load(f)
            _ticker_mapping_cache = _parse_ticker_mapping(raw_data)
            _ensure_background_refresh(user_agent)
            return _ticker_mapping_cache

    print("  Fetching company_tickers.json from SEC...")
    try:
        data = _fetch_company_tickers_raw(user_agent)
    except SECMappingUnavailableError as e:
        if cache_file.exists():
            print(f"  WARNING: {e} — using cached copy from disk")
            with open(cache_file, "r") as f:
                raw_data = json.load(f)
            _ticker_mapping_cache = _parse_ticker_mapping(raw_data)
            return _ticker_mapping_cache
        if BUNDLED_TICKERS_FILE.exists():
            print(f"  WARNING: {e} — using bundled fallback copy")
            with open(BUNDLED_TICKERS_FILE, "r") as f:
                raw_data = json.load(f)
            _ticker_mapping_cache = _parse_ticker_mapping(raw_data)
            return _ticker_mapping_cache
        raise

    with open(cache_file, "w") as f:
        json.dump(data, f)

    _ticker_mapping_cache = _parse_ticker_mapping(data)
    _ensure_background_refresh(user_agent)
    return _ticker_mapping_cache


def _parse_ticker_mapping(raw_data: dict) -> dict:
    """Parse SEC ticker JSON into ticker -> CIK mapping."""
    mapping = {}
    for entry in raw_data.values():
        ticker = entry.get("ticker", "").upper()
        cik = entry.get("cik_str")
        if ticker and cik:
            mapping[ticker] = int(cik)
    return mapping


def resolve_ticker_to_cik(ticker: str, user_agent: str) -> Optional[int]:
    """
    Resolve a ticker symbol to its CIK.

    Handles ticker format variations:
    - SEC uses dashes (BRK-B) while markets often use dots (BRK.B)
    - Tries dash format first, then original format as fallback

    Returns None only once the mapping has actually loaded and the ticker
    genuinely isn't in it. If the mapping itself can't be loaded (e.g. SEC
    rate-limiting company_tickers.json, with no cached/bundled fallback),
    load_ticker_to_cik_mapping() raises SECMappingUnavailableError instead —
    that's a different failure and must not be reported as "not found".
    """
    ticker = ticker.upper()
    mapping = load_ticker_to_cik_mapping(user_agent)

    ticker_dash = ticker.replace(".", "-")
    if ticker_dash in mapping:
        if ticker_dash != ticker:
            print(f"  Ticker normalized: {ticker} -> {ticker_dash}")
        return mapping[ticker_dash]

    if ticker in mapping:
        return mapping[ticker]

    print(f"  ERROR: Ticker '{ticker}' not found in SEC mapping (tried: {ticker_dash}, {ticker})")
    return None


def format_cik(cik: int) -> str:
    """Format CIK as 10-digit zero-padded string."""
    return str(cik).zfill(10)


def fetch_company_facts(cik: int, user_agent: str) -> Optional[dict]:
    """Fetch CompanyFacts from SEC EDGAR XBRL API."""
    cik_padded = format_cik(cik)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    return fetch_sec_endpoint(url, user_agent)


def fetch_company_submissions(cik: int, user_agent: str) -> Optional[dict]:
    """Fetch company submissions metadata (SIC code, name, fiscal year end)."""
    cik_padded = format_cik(cik)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    return fetch_sec_endpoint(url, user_agent)


# ============================================================================
# XBRL CONCEPT EXTRACTION (carried over from AIO LBO)
# ============================================================================

def _period_days(start_date: str, end_date: str) -> Optional[int]:
    """Days between two ISO yyyy-mm-dd date strings, or None if unparseable."""
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        return (end - start).days
    except (TypeError, ValueError):
        return None


def extract_concept_values(
    facts: dict,
    concept_name: str,
    taxonomy: str = "us-gaap",
    form_filter: str = "10-K",
    max_years: int = 10
) -> list:
    """
    Extract historical values for a specific XBRL concept from CompanyFacts.

    Returns a list of dicts with keys: fiscal_year, end_date, value, form, filed
    Sorted by fiscal year descending (most recent first).

    IMPORTANT (fiscal-year attribution fix): in SEC companyfacts, the `fy`/`fp`
    fields denote the fiscal year of the FILING, and each 10-K also carries
    comparative prior-period facts tagged with that same `fy`. The entry whose
    period `end` is latest within a `fy` group is the filing's own actual
    period; earlier ends are comparatives. Dedup therefore keys on `fy` but
    selects by latest `end` (tiebreak: latest `filed`) — NOT by `filed` alone,
    which misattributed comparative values to the filing year. Duration facts
    are additionally required to span roughly a full year, since some filers
    tag Q4/interim durations with fp=FY inside 10-K filings.
    """
    results = []

    try:
        concept_data = facts["facts"][taxonomy][concept_name]
        units_data = concept_data.get("units", {})

        for unit_key, entries in units_data.items():
            for entry in entries:
                form = entry.get("form", "")

                if form_filter and form != form_filter:
                    continue

                fy = entry.get("fy")
                fp = entry.get("fp")
                start_date = entry.get("start")
                end_date = entry.get("end")
                val = entry.get("val")
                filed = entry.get("filed")

                # Only include full-year filings
                if fp and fp != "FY":
                    continue

                # Duration facts (have a start date) must span ~a full fiscal
                # year (52/53-week years are 364/371 days). Some filers tag
                # Q4/interim durations with fp=FY inside 10-K filings.
                if start_date and end_date:
                    days = _period_days(start_date, end_date)
                    if days is not None and not (300 <= days <= 400):
                        continue

                if fy and val is not None:
                    results.append({
                        "fiscal_year": fy,
                        "end_date": end_date,
                        "value": val,
                        "form": form,
                        "filed": filed,
                        "unit": unit_key
                    })

    except KeyError:
        return []

    # Deduplicate by fiscal year: within a fy group, the latest period end is
    # the filing's own actual period (earlier ends are comparatives carried in
    # the same filing). Tiebreak equal ends by latest filed date.
    seen_years = {}
    for r in results:
        fy = r["fiscal_year"]
        if fy not in seen_years:
            seen_years[fy] = r
        else:
            cur = seen_years[fy]
            r_end, cur_end = (r.get("end_date") or ""), (cur.get("end_date") or "")
            if r_end > cur_end:
                seen_years[fy] = r
            elif r_end == cur_end and (r.get("filed") or "") > (cur.get("filed") or ""):
                seen_years[fy] = r

    sorted_results = sorted(seen_years.values(), key=lambda x: x["fiscal_year"], reverse=True)
    return sorted_results[:max_years]


def extract_with_fallbacks(
    facts: dict,
    concept_names: list,
    taxonomy: str = "us-gaap",
    friendly_name: str = "",
    form_filter: str = "10-K",
    max_years: int = 10,
    verbose: bool = True
) -> tuple:
    """
    Try to extract values for a concept, merging data from all matching tags.

    Companies often switch XBRL tags between filings (e.g., AAPL switched from
    "Revenues" to "RevenueFromContractWithCustomerExcludingAssessedTax").
    This function merges data from all tags to get complete history.

    Returns (values_list, matched_tags_string).
    If no concept found, returns ([], "MISSING").
    """
    merged_by_year = {}
    tags_used = []

    for concept in concept_names:
        values = extract_concept_values(
            facts, concept, taxonomy, form_filter, max_years * 2
        )
        if values:
            tags_used.append(concept)
            for v in values:
                fy = v["fiscal_year"]
                if fy not in merged_by_year:
                    merged_by_year[fy] = (v, concept)
                else:
                    existing_v, _ = merged_by_year[fy]
                    # Same end-first preference as extract_concept_values:
                    # the latest period end for a fy is the actual period.
                    v_end = v.get("end_date") or ""
                    e_end = existing_v.get("end_date") or ""
                    if v_end > e_end:
                        merged_by_year[fy] = (v, concept)
                    elif v_end == e_end and (v.get("filed") or "") > (existing_v.get("filed") or ""):
                        merged_by_year[fy] = (v, concept)

    if not merged_by_year:
        if verbose:
            print(f"  MISSING: {friendly_name} (tried: {concept_names})")
        return [], "MISSING"

    result = []
    for fy in sorted(merged_by_year.keys(), reverse=True)[:max_years]:
        val_dict, tag = merged_by_year[fy]
        val_dict["_matched_tag"] = tag
        result.append(val_dict)

    if len(tags_used) == 1:
        if verbose:
            print(f"  {friendly_name}: matched tag '{tags_used[0]}'")
        tag_str = tags_used[0]
    else:
        if verbose:
            print(f"  {friendly_name}: matched multiple tags {tags_used}")
        tag_str = " + ".join(tags_used)

    return result, tag_str


def extract_da_with_sum_fallback(facts: dict, verbose: bool = True) -> tuple:
    """
    Extract D&A with fallback to summing separate Depreciation + Amortization
    tags (some companies, e.g. MSFT/POOL, report them separately).
    Carried over from AIO LBO.
    """
    current_year = datetime.now().year

    da_vals, da_tag = extract_with_fallbacks(
        facts,
        [
            "DepreciationDepletionAndAmortization",
            "DepreciationAndAmortization",
            "DepreciationAmortizationAndAccretionNet",  # DECK uses this
        ],
        friendly_name="D&A (combined)",
        verbose=False
    )

    if da_vals:
        most_recent_fy = max(v.get("fiscal_year", 0) for v in da_vals)
        if current_year - most_recent_fy <= 2:
            if verbose:
                print(f"  D&A: matched combined tag '{da_tag}'")
            return da_vals, da_tag
        else:
            if verbose:
                print(f"  D&A: combined tag data stale (FY{most_recent_fy}), trying fallback...")

    depreciation_vals = extract_concept_values(
        facts, "Depreciation", "us-gaap", "10-K", max_years=10
    )
    amortization_vals = extract_concept_values(
        facts, "AmortizationOfIntangibleAssets", "us-gaap", "10-K", max_years=10
    )

    if depreciation_vals or amortization_vals:
        merged = {}

        for source_name, vals in [("Depreciation", depreciation_vals),
                                  ("AmortizationOfIntangibleAssets", amortization_vals)]:
            for v in vals:
                fy = v["fiscal_year"]
                if fy not in merged:
                    merged[fy] = {"fiscal_year": fy, "value": 0, "end_date": v.get("end_date"),
                                  "filed": v.get("filed"), "_components": []}
                merged[fy]["value"] += v["value"]
                merged[fy]["_components"].append(source_name)
                if v.get("filed") and (not merged[fy].get("filed") or v["filed"] > merged[fy]["filed"]):
                    merged[fy]["filed"] = v["filed"]

        result = sorted(merged.values(), key=lambda x: x["fiscal_year"], reverse=True)[:10]

        if result:
            has_depr = any("Depreciation" in r.get("_components", []) for r in result)
            has_amort = any("AmortizationOfIntangibleAssets" in r.get("_components", []) for r in result)

            if has_depr and has_amort:
                tag_str = "Depreciation + AmortizationOfIntangibleAssets (summed)"
            elif has_depr:
                tag_str = "Depreciation (only)"
            else:
                tag_str = "AmortizationOfIntangibleAssets (only)"

            if verbose:
                print(f"  D&A: matched separate tags -> {tag_str}")
            return result, tag_str

    if verbose:
        print(f"  MISSING: D&A (tried: combined tags, separate Depreciation + Amortization)")
    return [], "MISSING"


def extract_operating_income_with_fallbacks(facts: dict, verbose: bool = True) -> tuple:
    """
    Extract operating income with intelligent fallbacks. Carried over from AIO LBO.

    Fallback priority:
    1. OperatingIncomeLoss (direct XBRL tag)
    2. GrossProfit - SG&A - R&D (calculated proxy)
    3. Pre-tax income (last resort)

    Returns (values_list, tag_description, substitute_flag).
    """
    current_year = datetime.now().year

    op_income_vals, op_income_tag = extract_with_fallbacks(
        facts,
        ["OperatingIncomeLoss"],
        friendly_name="Operating Income",
        verbose=False
    )

    if op_income_vals:
        most_recent_fy = max(v.get("fiscal_year", 0) for v in op_income_vals)
        if current_year - most_recent_fy <= 2:
            if verbose:
                print(f"  Operating Income: matched tag 'OperatingIncomeLoss'")
            return op_income_vals, op_income_tag, None
        else:
            if verbose:
                print(f"  Operating Income: OperatingIncomeLoss stale (FY{most_recent_fy}), trying calculated fallback...")

    gross_profit_vals = extract_concept_values(
        facts, "GrossProfit", "us-gaap", "10-K", max_years=10
    )
    sga_vals = extract_concept_values(
        facts, "SellingGeneralAndAdministrativeExpense", "us-gaap", "10-K", max_years=10
    )
    rnd_vals = extract_concept_values(
        facts, "ResearchAndDevelopmentExpense", "us-gaap", "10-K", max_years=10
    )

    if gross_profit_vals and sga_vals:
        gp_by_year = {v["fiscal_year"]: v["value"] for v in gross_profit_vals}
        sga_by_year = {v["fiscal_year"]: v["value"] for v in sga_vals}
        rnd_by_year = {v["fiscal_year"]: v["value"] for v in rnd_vals} if rnd_vals else {}

        calculated_vals = []
        for gp_entry in gross_profit_vals:
            fy = gp_entry["fiscal_year"]
            if fy in sga_by_year:
                gp = gp_by_year[fy]
                sga = sga_by_year[fy]
                rnd = rnd_by_year.get(fy, 0)
                calc_op_inc = gp - sga - rnd

                calculated_vals.append({
                    "fiscal_year": fy,
                    "end_date": gp_entry.get("end_date"),
                    "value": calc_op_inc,
                    "form": gp_entry.get("form"),
                    "filed": gp_entry.get("filed"),
                    "_components": f"GrossProfit({gp/1e9:.1f}B) - SG&A({sga/1e9:.1f}B) - R&D({rnd/1e9:.1f}B)"
                })

        if calculated_vals:
            most_recent_fy = max(v["fiscal_year"] for v in calculated_vals)
            if current_year - most_recent_fy <= 2:
                tag_str = "GrossProfit - SG&A - R&D (calculated)"
                if verbose:
                    print(f"  Operating Income: using calculated fallback ({tag_str})")
                return calculated_vals, tag_str, "CALCULATED"

    pretax_vals, pretax_tag = extract_with_fallbacks(
        facts,
        ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
        friendly_name="Operating Income (pre-tax fallback)",
        verbose=False
    )

    if pretax_vals:
        tag_str = "IncomeLossFromContinuingOperations... (PRE-TAX SUBSTITUTE)"
        if verbose:
            print(f"  Operating Income: WARNING - using pre-tax income as substitute")
        return pretax_vals, tag_str, "PRETAX_SUBSTITUTE"

    if verbose:
        print(f"  MISSING: Operating Income (tried: OperatingIncomeLoss, calculated, pre-tax)")
    return [], "MISSING", None


def extract_liabilities_with_fallbacks(facts: dict, verbose: bool = True) -> tuple:
    """
    Extract Total Liabilities. AIO LBO's testing showed the direct
    `Liabilities` tag has real gaps for some companies, so this adds a
    calculated fallback: LiabilitiesAndStockholdersEquity - StockholdersEquity.

    Returns (values_list, tag_description, substitute_flag).
    """
    liab_vals, liab_tag = extract_with_fallbacks(
        facts,
        ["Liabilities"],
        friendly_name="Total Liabilities",
        verbose=False
    )

    if liab_vals:
        if verbose:
            print(f"  Total Liabilities: matched tag '{liab_tag}'")
        return liab_vals, liab_tag, None

    # Calculated fallback: Total Assets (= L&SE) minus Stockholders' Equity
    lse_vals = extract_concept_values(
        facts, "LiabilitiesAndStockholdersEquity", "us-gaap", "10-K", max_years=10
    )
    equity_vals, _equity_tag = extract_with_fallbacks(
        facts,
        [
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            "StockholdersEquity",
        ],
        friendly_name="Stockholders Equity (for liabilities fallback)",
        verbose=False
    )

    if lse_vals and equity_vals:
        eq_by_year = {v["fiscal_year"]: v["value"] for v in equity_vals}
        calculated = []
        for lse in lse_vals:
            fy = lse["fiscal_year"]
            if fy in eq_by_year:
                calculated.append({
                    "fiscal_year": fy,
                    "end_date": lse.get("end_date"),
                    "value": lse["value"] - eq_by_year[fy],
                    "form": lse.get("form"),
                    "filed": lse.get("filed"),
                    "_components": "LiabilitiesAndStockholdersEquity - StockholdersEquity"
                })
        if calculated:
            tag_str = "LiabilitiesAndStockholdersEquity - StockholdersEquity (calculated)"
            if verbose:
                print(f"  Total Liabilities: using calculated fallback ({tag_str})")
            return calculated, tag_str, "CALCULATED"

    if verbose:
        print(f"  MISSING: Total Liabilities (tried: Liabilities, calculated L&SE - equity)")
    return [], "MISSING", None


def extract_all_financials(facts: dict, ticker: str, verbose: bool = True) -> dict:
    """
    Extract all financial concepts needed for M&A modeling from CompanyFacts.
    Returns a dict with extracted values and metadata about which tags matched.
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"EXTRACTING FINANCIAL DATA FOR {ticker}")
        print(f"{'='*60}")

    extracted = {
        "tag_matches": {},
        "substitute_flags": {},
        "data": {}
    }

    # Revenue (proven AIO LBO fallback list)
    revenue_vals, revenue_tag = extract_with_fallbacks(
        facts,
        ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        friendly_name="Revenue",
        verbose=verbose
    )
    extracted["tag_matches"]["revenue"] = revenue_tag
    extracted["data"]["revenue"] = revenue_vals

    # Operating Income
    op_income_vals, op_income_tag, op_income_flag = extract_operating_income_with_fallbacks(
        facts, verbose=verbose
    )
    extracted["tag_matches"]["operating_income"] = op_income_tag
    extracted["data"]["operating_income"] = op_income_vals
    if op_income_flag:
        extracted["substitute_flags"]["operating_income"] = op_income_flag

    # D&A
    da_vals, da_tag = extract_da_with_sum_fallback(facts, verbose=verbose)
    extracted["tag_matches"]["da"] = da_tag
    extracted["data"]["da"] = da_vals

    # NEW FOR M&A: Net Income
    ni_vals, ni_tag = extract_with_fallbacks(
        facts,
        [
            "NetIncomeLoss",
            "ProfitLoss",
            "NetIncomeLossAvailableToCommonStockholdersBasic",
            "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
        ],
        friendly_name="Net Income",
        verbose=verbose
    )
    extracted["tag_matches"]["net_income"] = ni_tag
    extracted["data"]["net_income"] = ni_vals

    # NEW FOR M&A: Diluted EPS. Last-resort fallback to basic EPS for
    # companies with no dilutive instruments that only file basic
    # (e.g. BRK.B) — flagged as BASIC_SUBSTITUTE, not silently substituted.
    eps_vals, eps_tag = extract_with_fallbacks(
        facts,
        [
            "EarningsPerShareDiluted",
            "EarningsPerShareBasicAndDiluted",
            "IncomeLossFromContinuingOperationsPerDilutedShare",
        ],
        friendly_name="Diluted EPS",
        verbose=verbose
    )
    if not eps_vals:
        basic_vals, basic_tag = extract_with_fallbacks(
            facts,
            ["EarningsPerShareBasic"],
            friendly_name="Diluted EPS (basic fallback)",
            verbose=False
        )
        # Only accept the basic substitute if it's current data — some
        # companies (e.g. BRK) stopped filing standard EPS tags years ago,
        # and stale numbers are worse than an honest MISSING.
        if basic_vals:
            most_recent_fy = max(v.get("fiscal_year", 0) for v in basic_vals)
            if datetime.now().year - most_recent_fy <= 2:
                eps_vals = basic_vals
                eps_tag = f"{basic_tag} (BASIC SUBSTITUTE)"
                extracted["substitute_flags"]["diluted_eps"] = "BASIC_SUBSTITUTE"
                if verbose:
                    print(f"  Diluted EPS: WARNING - using basic EPS as substitute "
                          f"(no diluted tag filed; company likely has no dilutive instruments)")
            elif verbose:
                print(f"  Diluted EPS: basic fallback stale (FY{most_recent_fy}), treating as MISSING")
        if not eps_vals and verbose:
            print(f"  MISSING: Diluted EPS (tried diluted tags + recent basic substitute)")
    extracted["tag_matches"]["diluted_eps"] = eps_tag
    extracted["data"]["diluted_eps"] = eps_vals

    # NEW FOR M&A: Diluted (weighted-average) shares outstanding.
    # dei:EntityCommonStockSharesOutstanding is basic shares at a point in
    # time; accretion/dilution math needs EPS-consistent diluted shares.
    # Same basic-substitute last resort as diluted EPS, flagged.
    dil_shares_vals, dil_shares_tag = extract_with_fallbacks(
        facts,
        [
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted",
        ],
        friendly_name="Diluted Shares Outstanding (weighted avg)",
        verbose=verbose
    )
    if not dil_shares_vals:
        basic_sh_vals, basic_sh_tag = extract_with_fallbacks(
            facts,
            ["WeightedAverageNumberOfSharesOutstandingBasic"],
            friendly_name="Diluted Shares (basic fallback)",
            verbose=False
        )
        # Same staleness guard as the EPS basic substitute above.
        if basic_sh_vals:
            most_recent_fy = max(v.get("fiscal_year", 0) for v in basic_sh_vals)
            if datetime.now().year - most_recent_fy <= 2:
                dil_shares_vals = basic_sh_vals
                dil_shares_tag = f"{basic_sh_tag} (BASIC SUBSTITUTE)"
                extracted["substitute_flags"]["diluted_shares"] = "BASIC_SUBSTITUTE"
                if verbose:
                    print(f"  Diluted Shares: WARNING - using basic weighted-average "
                          f"shares as substitute (no diluted tag filed)")
            elif verbose:
                print(f"  Diluted Shares: basic fallback stale (FY{most_recent_fy}), treating as MISSING")
        if not dil_shares_vals and verbose:
            print(f"  MISSING: Diluted Shares (tried diluted tags + recent basic substitute)")
    extracted["tag_matches"]["diluted_shares"] = dil_shares_tag
    extracted["data"]["diluted_shares"] = dil_shares_vals

    # NEW FOR M&A: Total Assets
    assets_vals, assets_tag = extract_with_fallbacks(
        facts,
        ["Assets"],
        friendly_name="Total Assets",
        verbose=verbose
    )
    extracted["tag_matches"]["total_assets"] = assets_tag
    extracted["data"]["total_assets"] = assets_vals

    # NEW FOR M&A: Total Liabilities (with calculated fallback)
    liab_vals, liab_tag, liab_flag = extract_liabilities_with_fallbacks(
        facts, verbose=verbose
    )
    extracted["tag_matches"]["total_liabilities"] = liab_tag
    extracted["data"]["total_liabilities"] = liab_vals
    if liab_flag:
        extracted["substitute_flags"]["total_liabilities"] = liab_flag

    # Total Debt (proven AIO LBO approach: noncurrent + current, then combined)
    ltd_nc_vals, ltd_nc_tag = extract_with_fallbacks(
        facts,
        ["LongTermDebtNoncurrent"],
        friendly_name="LT Debt Noncurrent",
        verbose=verbose
    )
    ltd_c_vals, ltd_c_tag = extract_with_fallbacks(
        facts,
        ["LongTermDebtCurrent"],
        friendly_name="LT Debt Current",
        verbose=verbose
    )
    debt_combined_vals, debt_combined_tag = extract_with_fallbacks(
        facts,
        ["DebtLongtermAndShorttermCombinedAmount", "LongTermDebt", "Debt"],
        friendly_name="Total Debt Combined",
        verbose=verbose
    )
    extracted["tag_matches"]["ltd_noncurrent"] = ltd_nc_tag
    extracted["tag_matches"]["ltd_current"] = ltd_c_tag
    extracted["tag_matches"]["debt_combined"] = debt_combined_tag
    extracted["data"]["ltd_noncurrent"] = ltd_nc_vals
    extracted["data"]["ltd_current"] = ltd_c_vals
    extracted["data"]["debt_combined"] = debt_combined_vals

    # Cash
    cash_vals, cash_tag = extract_with_fallbacks(
        facts,
        ["CashAndCashEquivalentsAtCarryingValue"],
        friendly_name="Cash",
        verbose=verbose
    )
    extracted["tag_matches"]["cash"] = cash_tag
    extracted["data"]["cash"] = cash_vals

    # CapEx
    capex_vals, capex_tag = extract_with_fallbacks(
        facts,
        ["PaymentsToAcquirePropertyPlantAndEquipment"],
        friendly_name="CapEx",
        verbose=verbose
    )
    extracted["tag_matches"]["capex"] = capex_tag
    extracted["data"]["capex"] = capex_vals

    # Basic shares outstanding (dei taxonomy, point-in-time)
    shares_vals, shares_tag = extract_with_fallbacks(
        facts,
        ["EntityCommonStockSharesOutstanding"],
        taxonomy="dei",
        friendly_name="Shares Outstanding (basic, point-in-time)",
        form_filter=None,
        verbose=verbose
    )
    extracted["tag_matches"]["shares_outstanding"] = shares_tag
    extracted["data"]["shares_outstanding"] = shares_vals

    return extracted


# ============================================================================
# TWELVE DATA CLIENT (carried over from AIO LBO)
# ============================================================================

# Twelve Data free tier: 8 requests/minute -> 8s between requests to be safe
TWELVE_DATA_REQUEST_DELAY = 8.0
_last_twelve_data_request_time = 0.0


def _twelve_data_rate_limit():
    """Enforce Twelve Data rate limit (8 requests/minute for free tier)."""
    global _last_twelve_data_request_time
    elapsed = time.time() - _last_twelve_data_request_time
    if elapsed < TWELVE_DATA_REQUEST_DELAY:
        sleep_time = TWELVE_DATA_REQUEST_DELAY - elapsed
        print(f"  (rate limit: waiting {sleep_time:.1f}s)", end="", flush=True)
        time.sleep(sleep_time)
    _last_twelve_data_request_time = time.time()


def get_twelve_data_api_key() -> str:
    """Read Twelve Data API key from environment variable (server-side key)."""
    api_key = os.environ.get("TWELVE_DATA_API_KEY")
    if not api_key:
        raise ValueError(
            "TWELVE_DATA_API_KEY environment variable not set.\n"
            "Set it with: set TWELVE_DATA_API_KEY=your_key_here (Windows) or\n"
            "export TWELVE_DATA_API_KEY=your_key_here (Unix)"
        )
    return api_key


def fetch_current_price(ticker: str, api_key: str) -> Optional[float]:
    """
    Fetch current share price from Twelve Data quote endpoint.
    Returns the current price as a float, or None if unavailable.
    """
    _twelve_data_rate_limit()

    url = "https://api.twelvedata.com/quote"
    params = {
        "symbol": ticker,
        "apikey": api_key
    }

    try:
        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 429:
            print(f"  ERROR: Twelve Data rate limit exceeded")
            return None

        if response.status_code != 200:
            print(f"  ERROR: Twelve Data HTTP {response.status_code}")
            return None

        data = response.json()

        if data.get("status") == "error":
            print(f"  ERROR: Twelve Data - {data.get('message', 'Unknown error')}")
            return None

        price = data.get("close")
        if price is None:
            price = data.get("previous_close")

        if price is not None:
            return float(price)

        print(f"  ERROR: No price field in Twelve Data response")
        return None

    except requests.exceptions.Timeout:
        print(f"  ERROR: Twelve Data request timeout")
        return None
    except requests.exceptions.ConnectionError:
        print(f"  ERROR: Twelve Data connection error")
        return None
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  ERROR: Twelve Data response parsing error: {e}")
        return None


# ============================================================================
# COMPANY PROFILE ASSEMBLY
# ============================================================================

def build_company_profile(
    ticker: str,
    cik: int,
    submissions: dict,
    extracted: dict,
    current_price: Optional[float],
    verbose: bool = True
) -> dict:
    """
    Build a clean company profile object for one ticker, using AIO LBO's
    missing-field flagging convention (explicit "MISSING: {concept}" prints
    plus a missing_fields list in the returned object).
    """
    profile = {
        "ticker": ticker,
        "company_name": submissions.get("name", "Unknown"),
        "cik": cik,
        "sic_code": submissions.get("sic", "Unknown"),
        "sic_description": submissions.get("sicDescription", "Unknown"),
        "fiscal_year_end": submissions.get("fiscalYearEnd", "Unknown"),
        "current_price": current_price,
        "current_price_source": "Twelve Data" if current_price is not None else "MISSING",
        "shares_outstanding": None,
        "shares_outstanding_date": None,
        "diluted_shares": None,
        "diluted_shares_fy": None,
        "tag_matches": extracted["tag_matches"],
        "substitute_flags": extracted.get("substitute_flags", {}),
        "fiscal_years": {},
        "missing_fields": []
    }

    # Basic shares outstanding (most recent point-in-time value)
    shares_data = extracted["data"].get("shares_outstanding", [])
    if shares_data:
        profile["shares_outstanding"] = shares_data[0]["value"]
        profile["shares_outstanding_date"] = shares_data[0].get("end_date")
    else:
        profile["missing_fields"].append("shares_outstanding")
        if verbose:
            print(f"  MISSING: shares_outstanding ({ticker})")

    # Diluted shares (most recent fiscal year, weighted average)
    dil_shares_data = extracted["data"].get("diluted_shares", [])
    if dil_shares_data:
        profile["diluted_shares"] = dil_shares_data[0]["value"]
        profile["diluted_shares_fy"] = dil_shares_data[0]["fiscal_year"]
    else:
        profile["missing_fields"].append("diluted_shares")
        if verbose:
            print(f"  MISSING: diluted_shares ({ticker})")

    # Determine fiscal years to report (last 5, anchored on revenue history)
    revenue_data = extracted["data"].get("revenue", [])
    fiscal_years = [r["fiscal_year"] for r in revenue_data[:5]]

    if not fiscal_years:
        for key in ["net_income", "operating_income", "total_assets", "cash"]:
            data = extracted["data"].get(key, [])
            if data:
                fiscal_years = [r["fiscal_year"] for r in data[:5]]
                break

    def get_value_for_year(data_list: list, fy: int) -> Optional[float]:
        for item in data_list:
            if item["fiscal_year"] == fy:
                return item["value"]
        return None

    CONCEPT_KEYS = [
        "revenue", "operating_income", "da", "net_income", "diluted_eps",
        "diluted_shares", "total_assets", "total_liabilities", "cash", "capex",
    ]

    for fy in fiscal_years:
        year_data = {"fiscal_year": fy, "missing": []}

        for key in CONCEPT_KEYS:
            val = get_value_for_year(extracted["data"].get(key, []), fy)
            year_data[key] = val
            if val is None:
                year_data["missing"].append(key)

        # EBITDA (calculated)
        op_inc = year_data.get("operating_income")
        da = year_data.get("da")
        if op_inc is not None and da is not None:
            year_data["ebitda_calculated"] = op_inc + da
        else:
            year_data["ebitda_calculated"] = None
            year_data["missing"].append("ebitda_calculated (missing components)")

        # Total Debt - noncurrent + current first, then combined tag
        ltd_nc = get_value_for_year(extracted["data"].get("ltd_noncurrent", []), fy)
        ltd_c = get_value_for_year(extracted["data"].get("ltd_current", []), fy)
        debt_combined = get_value_for_year(extracted["data"].get("debt_combined", []), fy)

        if ltd_nc is not None or ltd_c is not None:
            year_data["total_debt"] = (ltd_nc or 0) + (ltd_c or 0)
            year_data["debt_breakdown"] = {"noncurrent": ltd_nc, "current": ltd_c}
        elif debt_combined is not None:
            year_data["total_debt"] = debt_combined
            year_data["debt_breakdown"] = "combined tag"
        else:
            year_data["total_debt"] = None
            year_data["missing"].append("total_debt")

        profile["fiscal_years"][fy] = year_data

    # Aggregate missing fields with the MISSING: convention
    for fy, fy_data in profile["fiscal_years"].items():
        for missing in fy_data.get("missing", []):
            profile["missing_fields"].append(f"{missing} (FY{fy})")
            if verbose and "missing components" not in missing:
                print(f"  MISSING: {missing} (FY{fy}) ({ticker})")

    return profile


def fetch_company(
    ticker: str,
    sec_user_agent: str,
    twelve_data_key: str = "",
    verbose: bool = True,
    skip_price: bool = False
) -> Optional[dict]:
    """
    Fetch the complete profile for one ticker from SEC EDGAR (+ Twelve Data
    price unless skipped). Returns the profile dict, or None on failure.
    """
    if verbose:
        print(f"\n[{ticker}] Resolving ticker to CIK...")
    cik = resolve_ticker_to_cik(ticker, sec_user_agent)
    if cik is None:
        return None
    if verbose:
        print(f"  CIK: {cik} (padded: {format_cik(cik)})")

    if verbose:
        print(f"[{ticker}] Fetching submissions metadata...")
    submissions = fetch_company_submissions(cik, sec_user_agent)
    if submissions is None:
        if verbose:
            print("  WARNING: Could not fetch submissions, proceeding without SIC code")
        submissions = {}
    elif verbose:
        print(f"  Company: {submissions.get('name')}")
        print(f"  SIC: {submissions.get('sic')} ({submissions.get('sicDescription')})")

    if verbose:
        print(f"[{ticker}] Fetching CompanyFacts...")
    facts = fetch_company_facts(cik, sec_user_agent)
    if facts is None:
        if verbose:
            print(f"  ERROR: Could not fetch CompanyFacts for {ticker}")
        return None

    extracted = extract_all_financials(facts, ticker, verbose=verbose)

    current_price = None
    if not skip_price and twelve_data_key:
        if verbose:
            print(f"[{ticker}] Fetching current price from Twelve Data...")
        current_price = fetch_current_price(ticker, twelve_data_key)
        if verbose:
            if current_price is not None:
                print(f"  Current price: ${current_price:.2f}")
            else:
                print(f"  WARNING: Could not fetch current price for {ticker}")

    return build_company_profile(ticker, cik, submissions, extracted,
                                 current_price, verbose=verbose)


# ============================================================================
# TWO-COMPANY M&A FETCH (the Phase 1 deliverable)
# ============================================================================

def fetch_ma_pair(
    acquirer_ticker: str,
    target_ticker: str,
    sec_user_agent: Optional[str] = None,
    twelve_data_key: Optional[str] = None,
    verbose: bool = True,
    skip_price: bool = False
) -> dict:
    """
    Fetch full profiles for an Acquirer and a Target in one call.

    Returns a structured object:
    {
        "acquirer": {profile or None},
        "target":  {profile or None},
        "fetch_status": {
            "acquirer": "OK" | "FAILED",
            "target":   "OK" | "FAILED"
        },
        "fetched_at": ISO timestamp
    }

    Both companies share the same global SEC rate limiter, so the doubled
    request volume of a two-company fetch stays under 10 req/sec.
    """
    # Compare post-normalization (dots -> dashes, as in resolve_ticker_to_cik)
    # so e.g. BRK.B vs BRK-B is caught as the same company.
    acq_norm = acquirer_ticker.strip().upper().replace(".", "-")
    tgt_norm = target_ticker.strip().upper().replace(".", "-")
    if acq_norm == tgt_norm:
        raise ValueError("Acquirer and Target must be different tickers")

    if sec_user_agent is None:
        sec_user_agent = get_sec_user_agent()

    if twelve_data_key is None:
        twelve_data_key = os.environ.get("TWELVE_DATA_API_KEY", "")

    result = {
        "acquirer": None,
        "target": None,
        "fetch_status": {"acquirer": "FAILED", "target": "FAILED"},
        # Populated only when a role's failure is a mapping-fetch failure
        # (e.g. SEC rate-limiting) rather than a genuine "ticker not found" —
        # validate_pair() surfaces this in place of the generic message.
        "fetch_errors": {},
        "fetched_at": datetime.now().isoformat(),
    }

    for role, ticker in [("acquirer", acquirer_ticker), ("target", target_ticker)]:
        if verbose:
            print(f"\n{'#'*60}")
            print(f"# {role.upper()}: {ticker.upper()}")
            print(f"{'#'*60}")
        try:
            profile = fetch_company(
                ticker.strip().upper(),
                sec_user_agent,
                twelve_data_key,
                verbose=verbose,
                skip_price=skip_price
            )
        except SECMappingUnavailableError as e:
            if verbose:
                print(f"  ERROR: {e}")
            result["fetch_errors"][role] = str(e)
            continue
        if profile is not None:
            profile["role"] = role
            result[role] = profile
            result["fetch_status"][role] = "OK"

    return result


# ============================================================================
# CLI TEST ENTRY POINT
# ============================================================================

def _print_profile_brief(profile: dict) -> None:
    """Print a compact view of one company profile."""
    print(f"\n--- {profile['role'].upper()}: {profile['ticker']} ---")
    print(f"  Company: {profile['company_name']} (CIK {profile['cik']})")
    print(f"  SIC: {profile['sic_code']} ({profile['sic_description']})")
    price = profile.get("current_price")
    print(f"  Price: {'$%.2f' % price if price is not None else 'MISSING'}")

    fys = sorted(profile["fiscal_years"].keys(), reverse=True)
    if not fys:
        print("  No fiscal year data")
        return
    fy = fys[0]
    d = profile["fiscal_years"][fy]

    def fmt(v, money=True):
        if v is None:
            return "MISSING"
        return f"${v/1e6:,.1f}M" if money else f"{v:,.2f}"

    print(f"  FY{fy}: Revenue {fmt(d.get('revenue'))}, NetIncome {fmt(d.get('net_income'))}, "
          f"EBITDA {fmt(d.get('ebitda_calculated'))}")
    print(f"         DilEPS {fmt(d.get('diluted_eps'), money=False)}, "
          f"DilShares {fmt(d.get('diluted_shares'), money=False)}, "
          f"Assets {fmt(d.get('total_assets'))}, Liab {fmt(d.get('total_liabilities'))}")
    if profile["missing_fields"]:
        print(f"  Missing fields: {len(profile['missing_fields'])}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python data_layer.py ACQUIRER_TICKER TARGET_TICKER [--with-price]")
        sys.exit(1)

    acq, tgt = sys.argv[1], sys.argv[2]
    with_price = "--with-price" in sys.argv

    pair = fetch_ma_pair(acq, tgt, skip_price=not with_price)

    print(f"\n{'='*60}")
    print("PAIR FETCH RESULT")
    print(f"{'='*60}")
    print(f"Status: acquirer={pair['fetch_status']['acquirer']}, "
          f"target={pair['fetch_status']['target']}")
    for role in ("acquirer", "target"):
        if pair[role]:
            _print_profile_brief(pair[role])
