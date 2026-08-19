"""
SEC EDGAR + Twelve Data Retrieval Test Script for AIO LBO
Primary data source: SEC EDGAR (free, no paywall for any filer)
Secondary source: Twelve Data (current share price only)
"""

import os
import sys
import json
import time
import requests
from pathlib import Path
from typing import Optional, Any
from datetime import datetime


# Allow command-line override for testing
# Usage: python sec_edgar_test.py [sec_email] [twelve_data_key]
if len(sys.argv) >= 2 and sys.argv[1]:
    os.environ["SEC_CONTACT_EMAIL"] = sys.argv[1]
if len(sys.argv) >= 3 and sys.argv[2]:
    os.environ["TWELVE_DATA_API_KEY"] = sys.argv[2]


# ============================================================================
# CONFIGURATION
# ============================================================================

# Cache directory for SEC data
CACHE_DIR = Path(__file__).parent / ".sec_cache"

# SEC rate limit: max 10 requests/second -> sleep 0.11s between requests
SEC_REQUEST_DELAY = 0.11

# Track last request time for rate limiting
_last_sec_request_time = 0.0


# ============================================================================
# SEC EDGAR CLIENT
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
    return f"AIO-LBO-Tool {email}"


def _sec_rate_limit():
    """Enforce SEC rate limit (max 10 requests/second)."""
    global _last_sec_request_time
    elapsed = time.time() - _last_sec_request_time
    if elapsed < SEC_REQUEST_DELAY:
        time.sleep(SEC_REQUEST_DELAY - elapsed)
    _last_sec_request_time = time.time()


def fetch_sec_endpoint(url: str, user_agent: str) -> Optional[dict]:
    """
    Fetch data from an SEC endpoint with rate limiting and error handling.
    """
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


def load_ticker_to_cik_mapping(user_agent: str) -> dict:
    """
    Load the SEC ticker->CIK mapping file.
    Caches locally to avoid repeated downloads.
    Returns dict mapping uppercase ticker -> CIK (as int).
    """
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / "company_tickers.json"

    # Use cached file if it exists and is less than 24 hours old
    if cache_file.exists():
        file_age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if file_age_hours < 24:
            print("  Using cached company_tickers.json")
            with open(cache_file, "r") as f:
                raw_data = json.load(f)
            return _parse_ticker_mapping(raw_data)

    # Fetch fresh copy
    print("  Fetching company_tickers.json from SEC...")
    url = "https://www.sec.gov/files/company_tickers.json"
    data = fetch_sec_endpoint(url, user_agent)

    if data is None:
        # Try to use stale cache if fetch failed
        if cache_file.exists():
            print("  WARNING: Using stale cache due to fetch failure")
            with open(cache_file, "r") as f:
                raw_data = json.load(f)
            return _parse_ticker_mapping(raw_data)
        return {}

    # Save to cache
    with open(cache_file, "w") as f:
        json.dump(data, f)
    print(f"  Cached to {cache_file}")

    return _parse_ticker_mapping(data)


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
    Resolve a ticker symbol to its CIK (Central Index Key).
    Returns the CIK as an integer, or None if not found.

    Handles ticker format variations:
    - SEC uses dashes (BRK-B) while markets often use dots (BRK.B)
    - Tries dash format first, then original format as fallback
    """
    ticker = ticker.upper()
    mapping = load_ticker_to_cik_mapping(user_agent)

    # Try dash format first (SEC standard)
    ticker_dash = ticker.replace(".", "-")
    if ticker_dash in mapping:
        if ticker_dash != ticker:
            print(f"  Ticker normalized: {ticker} -> {ticker_dash}")
        cik = mapping[ticker_dash]
        return cik

    # Try original format as fallback
    if ticker in mapping:
        cik = mapping[ticker]
        return cik

    print(f"  ERROR: Ticker '{ticker}' not found in SEC mapping (tried: {ticker_dash}, {ticker})")
    return None


def format_cik(cik: int) -> str:
    """Format CIK as 10-digit zero-padded string."""
    return str(cik).zfill(10)


def fetch_company_facts(cik: int, user_agent: str) -> Optional[dict]:
    """
    Fetch CompanyFacts from SEC EDGAR XBRL API.
    Returns the full JSON response.
    """
    cik_padded = format_cik(cik)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    print(f"  Fetching CompanyFacts for CIK {cik_padded}...")
    return fetch_sec_endpoint(url, user_agent)


def fetch_company_submissions(cik: int, user_agent: str) -> Optional[dict]:
    """
    Fetch company submissions metadata from SEC.
    This includes SIC code, company name, fiscal year end, etc.
    """
    cik_padded = format_cik(cik)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    print(f"  Fetching submissions metadata for CIK {cik_padded}...")
    return fetch_sec_endpoint(url, user_agent)


def print_companyfacts_structure(facts: dict) -> None:
    """
    Print the structure of the CompanyFacts response for inspection.
    Shows top-level keys and available us-gaap concepts.
    """
    print("\n" + "-"*60)
    print("COMPANYFACTS RESPONSE STRUCTURE")
    print("-"*60)

    # Top-level keys
    print(f"\nTop-level keys: {list(facts.keys())}")

    # Entity info
    if "entityName" in facts:
        print(f"Entity Name: {facts['entityName']}")

    # Available taxonomies
    if "facts" in facts:
        taxonomies = list(facts["facts"].keys())
        print(f"\nAvailable taxonomies: {taxonomies}")

        # Sample of us-gaap concepts
        if "us-gaap" in facts["facts"]:
            us_gaap = facts["facts"]["us-gaap"]
            concepts = list(us_gaap.keys())
            print(f"\nTotal us-gaap concepts available: {len(concepts)}")
            print("\nSample us-gaap concepts (first 30):")
            for concept in sorted(concepts)[:30]:
                print(f"  - {concept}")

            # Check for our target concepts
            print("\n--- Checking for TARGET concepts ---")
            targets = [
                "Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "OperatingIncomeLoss",
                "DepreciationDepletionAndAmortization",
                "DepreciationAndAmortization",
                "Assets",
                "Liabilities",
                "LongTermDebtNoncurrent",
                "LongTermDebtCurrent",
                "DebtLongtermAndShorttermCombinedAmount",
                "CashAndCashEquivalentsAtCarryingValue",
                "PaymentsToAcquirePropertyPlantAndEquipment",
            ]
            for target in targets:
                if target in us_gaap:
                    # Show a sample of the data structure
                    sample = us_gaap[target]
                    units = list(sample.get("units", {}).keys())
                    print(f"  FOUND: {target} (units: {units})")
                else:
                    print(f"  NOT FOUND: {target}")

        # Check dei taxonomy for shares outstanding
        if "dei" in facts["facts"]:
            dei = facts["facts"]["dei"]
            print(f"\nTotal dei concepts available: {len(dei.keys())}")
            shares_concept = "EntityCommonStockSharesOutstanding"
            if shares_concept in dei:
                print(f"  FOUND: dei:{shares_concept}")
            else:
                print(f"  NOT FOUND: dei:{shares_concept}")
                # Show what shares-related concepts exist
                shares_concepts = [k for k in dei.keys() if "share" in k.lower()]
                if shares_concepts:
                    print(f"  Available shares-related dei concepts: {shares_concepts}")


def extract_concept_values(
    facts: dict,
    concept_name: str,
    taxonomy: str = "us-gaap",
    form_filter: str = "10-K",
    max_years: int = 10
) -> list[dict]:
    """
    Extract historical values for a specific XBRL concept from CompanyFacts.

    Returns a list of dicts with keys: fiscal_year, end_date, value, form, filed
    Sorted by fiscal year descending (most recent first).
    """
    results = []

    try:
        concept_data = facts["facts"][taxonomy][concept_name]
        units_data = concept_data.get("units", {})

        # Usually in USD or shares
        for unit_key, entries in units_data.items():
            for entry in entries:
                form = entry.get("form", "")

                # Filter by form type if specified
                if form_filter and form != form_filter:
                    continue

                # Extract relevant fields
                fy = entry.get("fy")  # fiscal year
                fp = entry.get("fp")  # fiscal period (FY for annual)
                end_date = entry.get("end")
                val = entry.get("val")
                filed = entry.get("filed")

                # Only include full-year filings
                if fp and fp != "FY":
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

    # Deduplicate by fiscal year (take most recent filing per year)
    seen_years = {}
    for r in results:
        fy = r["fiscal_year"]
        if fy not in seen_years:
            seen_years[fy] = r
        else:
            # Keep the one with later filing date
            if r["filed"] > seen_years[fy]["filed"]:
                seen_years[fy] = r

    # Sort by fiscal year descending and limit
    sorted_results = sorted(seen_years.values(), key=lambda x: x["fiscal_year"], reverse=True)
    return sorted_results[:max_years]


def extract_with_fallbacks(
    facts: dict,
    concept_names: list[str],
    taxonomy: str = "us-gaap",
    friendly_name: str = "",
    form_filter: str = "10-K",
    max_years: int = 10,
    verbose: bool = True
) -> tuple[list[dict], str]:
    """
    Try to extract values for a concept, merging data from all matching tags.

    Companies often switch XBRL tags between filings (e.g., AAPL switched from
    "Revenues" to "RevenueFromContractWithCustomerExcludingAssessedTax").
    This function merges data from all tags to get complete history.

    Returns (values_list, matched_tags_string).
    If no concept found, returns ([], "MISSING").
    """
    merged_by_year = {}  # fiscal_year -> (value_dict, tag_name)
    tags_used = []

    for concept in concept_names:
        values = extract_concept_values(
            facts, concept, taxonomy, form_filter, max_years * 2  # Fetch extra to merge
        )
        if values:
            tags_used.append(concept)
            for v in values:
                fy = v["fiscal_year"]
                # Use the value if we don't have this year yet, or if this filing is newer
                if fy not in merged_by_year:
                    merged_by_year[fy] = (v, concept)
                else:
                    existing_v, _ = merged_by_year[fy]
                    if v["filed"] > existing_v["filed"]:
                        merged_by_year[fy] = (v, concept)

    if not merged_by_year:
        if verbose:
            print(f"  MISSING: {friendly_name} (tried: {concept_names})")
        return [], "MISSING"

    # Build result list sorted by fiscal year descending
    result = []
    for fy in sorted(merged_by_year.keys(), reverse=True)[:max_years]:
        val_dict, tag = merged_by_year[fy]
        val_dict["_matched_tag"] = tag  # Add tag info for debugging
        result.append(val_dict)

    # Report which tags were used
    if len(tags_used) == 1:
        if verbose:
            print(f"  {friendly_name}: matched tag '{tags_used[0]}'")
        tag_str = tags_used[0]
    else:
        if verbose:
            print(f"  {friendly_name}: matched multiple tags {tags_used}")
        tag_str = " + ".join(tags_used)

    return result, tag_str


# ============================================================================
# TWELVE DATA CLIENT
# ============================================================================

# Twelve Data free tier: 8 requests/minute -> 7.5s between requests to be safe
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
    """Read Twelve Data API key from environment variable."""
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
    # Enforce rate limit for free tier
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

        # Check for API error response
        if data.get("status") == "error":
            print(f"  ERROR: Twelve Data - {data.get('message', 'Unknown error')}")
            return None

        # Extract price (may be "close" or "previous_close" depending on market hours)
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
# DATA EXTRACTION AND SUMMARY
# ============================================================================

def extract_da_with_sum_fallback(
    facts: dict,
    verbose: bool = True
) -> tuple[list[dict], str]:
    """
    Extract D&A with fallback to summing separate Depreciation + Amortization tags.

    Some companies (e.g., MSFT, POOL) report depreciation and amortization as
    separate line items rather than a combined concept. This function:
    1. First tries combined tags (DepreciationDepletionAndAmortization, DepreciationAndAmortization,
       DepreciationAmortizationAndAccretionNet)
    2. If those fail OR are stale (3+ years old), looks for separate Depreciation +
       AmortizationOfIntangibleAssets and sums them

    Returns (values_list, matched_tag_description).
    """
    from datetime import datetime
    current_year = datetime.now().year

    # Try combined tags first
    da_vals, da_tag = extract_with_fallbacks(
        facts,
        [
            "DepreciationDepletionAndAmortization",
            "DepreciationAndAmortization",
            "DepreciationAmortizationAndAccretionNet",  # DECK uses this
        ],
        friendly_name="D&A (combined)",
        verbose=False  # We'll print our own message
    )

    # Check if data is recent enough (within 3 years)
    if da_vals:
        most_recent_fy = max(v.get("fiscal_year", 0) for v in da_vals)
        if current_year - most_recent_fy <= 2:
            # Data is recent, use it
            if verbose:
                print(f"  D&A: matched combined tag '{da_tag}'")
            return da_vals, da_tag
        else:
            # Data is stale, try fallback
            if verbose:
                print(f"  D&A: combined tag data stale (FY{most_recent_fy}), trying fallback...")

    # Fallback: try summing separate tags
    depreciation_vals = extract_concept_values(
        facts, "Depreciation", "us-gaap", "10-K", max_years=10
    )
    amortization_vals = extract_concept_values(
        facts, "AmortizationOfIntangibleAssets", "us-gaap", "10-K", max_years=10
    )

    if depreciation_vals or amortization_vals:
        # Merge by fiscal year, summing where both exist
        merged = {}

        for v in depreciation_vals:
            fy = v["fiscal_year"]
            if fy not in merged:
                merged[fy] = {"fiscal_year": fy, "value": 0, "end_date": v.get("end_date"),
                              "filed": v.get("filed"), "_components": []}
            merged[fy]["value"] += v["value"]
            merged[fy]["_components"].append("Depreciation")
            # Keep the later filing date
            if v.get("filed") and (not merged[fy].get("filed") or v["filed"] > merged[fy]["filed"]):
                merged[fy]["filed"] = v["filed"]

        for v in amortization_vals:
            fy = v["fiscal_year"]
            if fy not in merged:
                merged[fy] = {"fiscal_year": fy, "value": 0, "end_date": v.get("end_date"),
                              "filed": v.get("filed"), "_components": []}
            merged[fy]["value"] += v["value"]
            merged[fy]["_components"].append("AmortizationOfIntangibleAssets")
            if v.get("filed") and (not merged[fy].get("filed") or v["filed"] > merged[fy]["filed"]):
                merged[fy]["filed"] = v["filed"]

        # Build result sorted by fiscal year descending
        result = sorted(merged.values(), key=lambda x: x["fiscal_year"], reverse=True)[:10]

        if result:
            # Determine tag description based on what we found
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

    # Nothing found
    if verbose:
        print(f"  MISSING: D&A (tried: combined tags, separate Depreciation + Amortization)")
    return [], "MISSING"


def extract_operating_income_with_fallbacks(
    facts: dict,
    verbose: bool = True
) -> tuple[list[dict], str, str]:
    """
    Extract operating income with intelligent fallbacks.

    Fallback priority:
    1. OperatingIncomeLoss (direct XBRL tag)
    2. GrossProfit - SG&A - R&D (calculated proxy - closer to true operating income)
    3. Pre-tax income (last resort - includes non-operating items)

    Returns (values_list, tag_description, substitute_flag).
    substitute_flag will be:
    - None if using direct OperatingIncomeLoss
    - "CALCULATED" if using GrossProfit - SG&A - R&D
    - "PRETAX_SUBSTITUTE" if using pre-tax income
    """
    current_year = datetime.now().year

    # Try direct OperatingIncomeLoss first
    op_income_vals, op_income_tag = extract_with_fallbacks(
        facts,
        ["OperatingIncomeLoss"],
        friendly_name="Operating Income",
        verbose=False
    )

    # Check if data is recent enough (within 2 years)
    if op_income_vals:
        most_recent_fy = max(v.get("fiscal_year", 0) for v in op_income_vals)
        if current_year - most_recent_fy <= 2:
            if verbose:
                print(f"  Operating Income: matched tag 'OperatingIncomeLoss'")
            return op_income_vals, op_income_tag, None
        else:
            if verbose:
                print(f"  Operating Income: OperatingIncomeLoss stale (FY{most_recent_fy}), trying calculated fallback...")

    # Fallback 1: Try to calculate from GrossProfit - SG&A - R&D
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
        # Build year-indexed dicts
        gp_by_year = {v["fiscal_year"]: v["value"] for v in gross_profit_vals}
        sga_by_year = {v["fiscal_year"]: v["value"] for v in sga_vals}
        rnd_by_year = {v["fiscal_year"]: v["value"] for v in rnd_vals} if rnd_vals else {}

        # Calculate operating income for each year where we have GrossProfit and SG&A
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

    # Fallback 2: Use pre-tax income as last resort
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
            print(f"    Pre-tax income includes non-operating items (interest, other income/expense)")
            print(f"    EBITDA calculations will be distorted by non-operating items")
        return pretax_vals, tag_str, "PRETAX_SUBSTITUTE"

    # Nothing found
    if verbose:
        print(f"  MISSING: Operating Income (tried: OperatingIncomeLoss, calculated, pre-tax)")
    return [], "MISSING", None


def extract_all_financials(facts: dict, ticker: str, verbose: bool = True) -> dict:
    """
    Extract all target financial concepts from CompanyFacts.
    Returns a dict with extracted values and metadata about which tags matched.
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"EXTRACTING FINANCIAL DATA FOR {ticker}")
        print(f"{'='*60}")

    extracted = {
        "tag_matches": {},  # Which tag name matched for each concept
        "substitute_flags": {},  # Flags for concepts using substitute/proxy values
        "data": {}
    }

    # Revenue
    revenue_vals, revenue_tag = extract_with_fallbacks(
        facts,
        ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        friendly_name="Revenue",
        verbose=verbose
    )
    extracted["tag_matches"]["revenue"] = revenue_tag
    extracted["data"]["revenue"] = revenue_vals

    # Operating Income (with intelligent fallbacks)
    op_income_vals, op_income_tag, op_income_flag = extract_operating_income_with_fallbacks(
        facts, verbose=verbose
    )
    extracted["tag_matches"]["operating_income"] = op_income_tag
    extracted["data"]["operating_income"] = op_income_vals
    if op_income_flag:
        extracted["substitute_flags"]["operating_income"] = op_income_flag

    # D&A (with fallback to summing separate Depreciation + Amortization)
    da_vals, da_tag = extract_da_with_sum_fallback(facts, verbose=verbose)
    extracted["tag_matches"]["da"] = da_tag
    extracted["data"]["da"] = da_vals

    # Assets
    assets_vals, assets_tag = extract_with_fallbacks(
        facts,
        ["Assets"],
        friendly_name="Assets",
        verbose=verbose
    )
    extracted["tag_matches"]["assets"] = assets_tag
    extracted["data"]["assets"] = assets_vals

    # Liabilities
    liab_vals, liab_tag = extract_with_fallbacks(
        facts,
        ["Liabilities"],
        friendly_name="Liabilities",
        verbose=verbose
    )
    extracted["tag_matches"]["liabilities"] = liab_tag
    extracted["data"]["liabilities"] = liab_vals

    # Long-term debt (try noncurrent + current, then combined)
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

    # Shares Outstanding (from dei taxonomy)
    shares_vals, shares_tag = extract_with_fallbacks(
        facts,
        ["EntityCommonStockSharesOutstanding"],
        taxonomy="dei",
        friendly_name="Shares Outstanding",
        form_filter=None,  # Shares can come from various filings
        verbose=verbose
    )
    extracted["tag_matches"]["shares_outstanding"] = shares_tag
    extracted["data"]["shares_outstanding"] = shares_vals

    return extracted


def build_summary(
    ticker: str,
    cik: int,
    submissions: dict,
    extracted: dict,
    current_price: Optional[float],
    verbose: bool = True
) -> dict:
    """
    Build a clean summary object for one ticker.
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"BUILDING SUMMARY FOR {ticker}")
        print(f"{'='*60}")

    summary = {
        "ticker": ticker,
        "company_name": submissions.get("name", "Unknown"),
        "cik": cik,
        "sic_code": submissions.get("sic", "Unknown"),
        "sic_description": submissions.get("sicDescription", "Unknown"),
        "fiscal_year_end": submissions.get("fiscalYearEnd", "Unknown"),
        "current_price": current_price,
        "current_price_source": "Twelve Data" if current_price else "MISSING",
        "shares_outstanding": None,
        "shares_outstanding_date": None,
        "tag_matches": extracted["tag_matches"],
        "substitute_flags": extracted.get("substitute_flags", {}),
        "fiscal_years": {},
        "missing_fields": []
    }

    # Get shares outstanding (most recent value)
    shares_data = extracted["data"].get("shares_outstanding", [])
    if shares_data:
        summary["shares_outstanding"] = shares_data[0]["value"]
        summary["shares_outstanding_date"] = shares_data[0].get("end_date")
    else:
        summary["missing_fields"].append("shares_outstanding")

    # Build fiscal year data for last 5 years
    # First, find available fiscal years from revenue data
    revenue_data = extracted["data"].get("revenue", [])
    fiscal_years = [r["fiscal_year"] for r in revenue_data[:5]]

    if not fiscal_years:
        # Try to get years from other data
        for key in ["operating_income", "assets", "cash"]:
            data = extracted["data"].get(key, [])
            if data:
                fiscal_years = [r["fiscal_year"] for r in data[:5]]
                break

    # Helper to get value for a fiscal year
    def get_value_for_year(data_list: list, fy: int) -> Optional[float]:
        for item in data_list:
            if item["fiscal_year"] == fy:
                return item["value"]
        return None

    for fy in fiscal_years:
        year_data = {"fiscal_year": fy, "missing": []}

        # Revenue
        rev = get_value_for_year(extracted["data"].get("revenue", []), fy)
        year_data["revenue"] = rev
        if rev is None:
            year_data["missing"].append("revenue")

        # Operating Income
        op_inc = get_value_for_year(extracted["data"].get("operating_income", []), fy)
        year_data["operating_income"] = op_inc
        if op_inc is None:
            year_data["missing"].append("operating_income")

        # D&A
        da = get_value_for_year(extracted["data"].get("da", []), fy)
        year_data["da"] = da
        if da is None:
            year_data["missing"].append("da")

        # EBITDA (calculated)
        if op_inc is not None and da is not None:
            year_data["ebitda_calculated"] = op_inc + da
        else:
            year_data["ebitda_calculated"] = None
            year_data["missing"].append("ebitda_calculated (missing components)")

        # Total Debt - try noncurrent + current first, then combined
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

        # Cash
        cash = get_value_for_year(extracted["data"].get("cash", []), fy)
        year_data["cash"] = cash
        if cash is None:
            year_data["missing"].append("cash")

        # CapEx
        capex = get_value_for_year(extracted["data"].get("capex", []), fy)
        year_data["capex"] = capex
        if capex is None:
            year_data["missing"].append("capex")

        summary["fiscal_years"][fy] = year_data

    # Aggregate missing fields
    for fy, fy_data in summary["fiscal_years"].items():
        for missing in fy_data.get("missing", []):
            summary["missing_fields"].append(f"{missing} (FY{fy})")

    return summary


def print_summary(summary: dict) -> None:
    """Pretty print the summary object."""
    print(f"\n{'='*60}")
    print(f"FINAL SUMMARY: {summary['ticker']}")
    print(f"{'='*60}")

    print(f"\nCompany: {summary['company_name']}")
    print(f"CIK: {summary['cik']}")
    print(f"SIC Code: {summary['sic_code']} ({summary['sic_description']})")
    print(f"Fiscal Year End: {summary['fiscal_year_end']}")
    print(f"Current Price: ${summary['current_price']:.2f}" if summary['current_price'] else "Current Price: MISSING")

    shares = summary['shares_outstanding']
    if shares:
        print(f"Shares Outstanding: {shares:,.0f} (as of {summary['shares_outstanding_date']})")
    else:
        print("Shares Outstanding: MISSING")

    print(f"\n--- Tag Matches ---")
    for concept, tag in summary['tag_matches'].items():
        print(f"  {concept}: {tag}")

    print(f"\n--- Fiscal Year Data ---")
    for fy, data in sorted(summary['fiscal_years'].items(), reverse=True):
        print(f"\n  FY{fy}:")

        def fmt(val, label, divisor=1e6, suffix="M"):
            if val is not None:
                return f"${val/divisor:,.1f}{suffix}"
            return "MISSING"

        print(f"    Revenue:       {fmt(data.get('revenue'), 'Revenue')}")
        print(f"    Op. Income:    {fmt(data.get('operating_income'), 'Op Income')}")
        print(f"    D&A:           {fmt(data.get('da'), 'D&A')}")
        print(f"    EBITDA (calc): {fmt(data.get('ebitda_calculated'), 'EBITDA')}")
        print(f"    Total Debt:    {fmt(data.get('total_debt'), 'Debt')}")
        print(f"    Cash:          {fmt(data.get('cash'), 'Cash')}")
        print(f"    CapEx:         {fmt(data.get('capex'), 'CapEx')}")

        if data.get("missing"):
            print(f"    [Missing: {', '.join(data['missing'])}]")

    if summary['missing_fields']:
        print(f"\n{'!'*60}")
        print("ALL MISSING FIELDS:")
        for field in summary['missing_fields']:
            print(f"  - {field}")


# ============================================================================
# MAIN TEST FUNCTION
# ============================================================================

def fetch_ticker_data(
    ticker: str,
    sec_user_agent: str,
    twelve_data_key: str,
    verbose: bool = True,
    skip_price: bool = False
) -> Optional[dict]:
    """
    Fetch all data for a ticker from SEC EDGAR and Twelve Data.
    Returns a complete summary object.

    Args:
        verbose: If False, only print minimal progress info
        skip_price: If True, skip Twelve Data price fetch (for bulk testing)
    """
    if verbose:
        print(f"\n{'#'*60}")
        print(f"# PROCESSING: {ticker}")
        print(f"{'#'*60}")
        print(f"\n[1/5] Resolving ticker to CIK...")

    # Step 1: Resolve ticker to CIK
    cik = resolve_ticker_to_cik(ticker, sec_user_agent)
    if cik is None:
        return None
    if verbose:
        print(f"  CIK: {cik} (padded: {format_cik(cik)})")

    # Step 2: Fetch submissions metadata (for SIC code, company name)
    if verbose:
        print(f"\n[2/5] Fetching company submissions...")
    submissions = fetch_company_submissions(cik, sec_user_agent)
    if submissions is None:
        if verbose:
            print("  WARNING: Could not fetch submissions, proceeding without SIC code")
        submissions = {}
    else:
        if verbose:
            print(f"  Company: {submissions.get('name')}")
            print(f"  SIC: {submissions.get('sic')} ({submissions.get('sicDescription')})")

    # Step 3: Fetch CompanyFacts
    if verbose:
        print(f"\n[3/5] Fetching CompanyFacts...")
    facts = fetch_company_facts(cik, sec_user_agent)
    if facts is None:
        if verbose:
            print("  ERROR: Could not fetch CompanyFacts")
        return None

    # Print structure for inspection (only in verbose mode)
    if verbose:
        print_companyfacts_structure(facts)

    # Step 4: Extract financial data
    if verbose:
        print(f"\n[4/5] Extracting financial data...")
    extracted = extract_all_financials(facts, ticker, verbose=verbose)

    # Step 5: Fetch current price from Twelve Data (skip in bulk mode)
    current_price = None
    if not skip_price and twelve_data_key:
        if verbose:
            print(f"\n[5/5] Fetching current price from Twelve Data...")
        current_price = fetch_current_price(ticker, twelve_data_key)
        if verbose:
            if current_price:
                print(f"  Current price: ${current_price:.2f}")
            else:
                print("  WARNING: Could not fetch current price")

    # Build and return summary
    summary = build_summary(ticker, cik, submissions, extracted, current_price, verbose=verbose)
    return summary


# ============================================================================
# EXPANDED 20-TICKER TEST
# ============================================================================

# Test ticker categories
TICKER_CATEGORIES = {
    # Large-cap baseline
    "AAPL": {"category": "large-cap", "note": "Apple - clean baseline"},
    "MSFT": {"category": "large-cap", "note": "Microsoft - clean baseline"},
    "JNJ": {"category": "large-cap", "note": "Johnson & Johnson - clean baseline"},

    # Mid-cap
    "CROX": {"category": "mid-cap", "note": "Crocs"},
    "DECK": {"category": "mid-cap", "note": "Deckers Outdoor"},
    "POOL": {"category": "mid-cap", "note": "Pool Corp"},

    # Small-cap
    "FIZZ": {"category": "small-cap", "note": "National Beverage"},
    "SMPL": {"category": "small-cap", "note": "Simply Good Foods"},
    "WING": {"category": "small-cap", "note": "Wingstop"},

    # Debt-heavy (verify debt tags work)
    "CCL": {"category": "debt-heavy", "note": "Carnival - high leverage"},
    "AAL": {"category": "debt-heavy", "note": "American Airlines - high leverage"},
    "IRM": {"category": "debt-heavy", "note": "Iron Mountain - REIT-adjacent"},

    # Sectors for exclusion testing
    "JPM": {"category": "exclude-sector", "note": "Bank"},
    "AIG": {"category": "exclude-sector", "note": "Insurance"},
    "O": {"category": "exclude-sector", "note": "REIT"},
    "DUK": {"category": "exclude-sector", "note": "Utility"},

    # Recent IPO (limited history expected)
    "ARM": {"category": "recent-ipo", "note": "ARM Holdings - Sept 2023 IPO"},
    "RDDT": {"category": "recent-ipo", "note": "Reddit - March 2024 IPO"},

    # Edge cases
    "BRK.B": {"category": "edge-case", "note": "Berkshire - unusual structure"},
    "TSLA": {"category": "edge-case", "note": "Tesla - unconventional reporting"},
}

# Sectors that should be flagged for exclusion
EXCLUDE_SIC_RANGES = {
    "banks": (6000, 6199),
    "insurance": (6300, 6411),
    "reits": (6798, 6798),
    "utilities": (4900, 4999),
}


def analyze_tag_frequency(all_summaries: dict) -> dict:
    """
    Analyze which XBRL tags were used across all companies.
    Returns a dict mapping concept -> {tag_name: count}
    """
    tag_freq = {
        "revenue": {},
        "operating_income": {},
        "da": {},
        "assets": {},
        "liabilities": {},
        "ltd_noncurrent": {},
        "ltd_current": {},
        "debt_combined": {},
        "cash": {},
        "capex": {},
        "shares_outstanding": {},
    }

    for ticker, summary in all_summaries.items():
        tag_matches = summary.get("tag_matches", {})
        for concept, tag in tag_matches.items():
            if concept in tag_freq:
                if tag not in tag_freq[concept]:
                    tag_freq[concept][tag] = []
                tag_freq[concept][tag].append(ticker)

    return tag_freq


def check_sector_exclusion(sic_code: str) -> Optional[str]:
    """Check if SIC code falls in an exclusion range."""
    try:
        sic = int(sic_code)
        for sector, (low, high) in EXCLUDE_SIC_RANGES.items():
            if low <= sic <= high:
                return sector
    except (ValueError, TypeError):
        pass
    return None


def print_summary_table(all_summaries: dict, ticker_categories: dict):
    """Print a summary table of all tickers."""
    print(f"\n{'='*100}")
    print("SUMMARY TABLE: ALL TICKERS")
    print("="*100)

    # Header
    print(f"\n{'Ticker':<8} {'Category':<14} {'SIC':<6} {'Sector Flag':<12} {'FY Count':<8} {'Missing':<8} {'Missing Fields'}")
    print("-"*100)

    for ticker in ticker_categories.keys():
        summary = all_summaries.get(ticker)
        if summary is None:
            print(f"{ticker:<8} {'FAILED':<14} {'-':<6} {'-':<12} {'-':<8} {'-':<8} FETCH FAILED")
            continue

        category = ticker_categories[ticker]["category"]
        sic = summary.get("sic_code", "?")
        sector_flag = check_sector_exclusion(sic) or "-"
        fy_count = len(summary.get("fiscal_years", {}))

        # Count truly missing fields (concept-level, not year-level)
        missing_concepts = set()
        tag_matches = summary.get("tag_matches", {})
        for concept, tag in tag_matches.items():
            if tag == "MISSING":
                missing_concepts.add(concept)

        # Also check for years with missing data
        year_missing = []
        for fy, data in summary.get("fiscal_years", {}).items():
            for m in data.get("missing", []):
                if "missing components" not in m:  # Skip calculated fields
                    year_missing.append(f"{m}@FY{fy}")

        missing_count = len(missing_concepts) + len(year_missing)
        missing_str = ", ".join(sorted(missing_concepts)) if missing_concepts else ""
        if len(missing_str) > 30:
            missing_str = missing_str[:30] + "..."

        print(f"{ticker:<8} {category:<14} {sic:<6} {sector_flag:<12} {fy_count:<8} {missing_count:<8} {missing_str}")


def print_tag_frequency_table(tag_freq: dict):
    """Print tag usage frequency across all companies."""
    print(f"\n{'='*100}")
    print("TAG USAGE FREQUENCY TABLE")
    print("="*100)
    print("\nFor each concept, shows which XBRL tags matched and how many companies used each.\n")

    for concept, tags in tag_freq.items():
        print(f"\n--- {concept.upper()} ---")
        if not tags:
            print("  (no data)")
            continue

        # Sort by count descending
        sorted_tags = sorted(tags.items(), key=lambda x: len(x[1]), reverse=True)
        for tag, tickers in sorted_tags:
            ticker_list = ", ".join(tickers[:5])
            if len(tickers) > 5:
                ticker_list += f", ... (+{len(tickers)-5} more)"
            print(f"  {tag}: {len(tickers)} companies")
            print(f"    Used by: {ticker_list}")


def print_completely_missing_concepts(all_summaries: dict, ticker_categories: dict):
    """Flag tickers where a concept was missing across ALL fallback tags."""
    print(f"\n{'='*100}")
    print("COMPLETELY MISSING CONCEPTS (need manual inspection)")
    print("="*100)

    has_missing = False
    for ticker in ticker_categories.keys():
        summary = all_summaries.get(ticker)
        if summary is None:
            continue

        tag_matches = summary.get("tag_matches", {})
        missing = [k for k, v in tag_matches.items() if v == "MISSING"]

        if missing:
            has_missing = True
            print(f"\n{ticker} ({ticker_categories[ticker]['note']}):")
            print(f"  Missing concepts: {', '.join(missing)}")
            print(f"  Action: Inspect raw CompanyFacts JSON to find actual tag names")

    if not has_missing:
        print("\nNo tickers had completely missing concepts across all fallback tags.")


def print_debt_heavy_verification(all_summaries: dict):
    """Verify debt extraction for debt-heavy companies."""
    print(f"\n{'='*100}")
    print("DEBT-HEAVY TICKER VERIFICATION")
    print("="*100)
    print("\nConfirming total debt extraction returns plausible non-zero values:\n")

    debt_heavy_tickers = ["CCL", "AAL", "IRM"]

    for ticker in debt_heavy_tickers:
        summary = all_summaries.get(ticker)
        if summary is None:
            print(f"{ticker}: FAILED TO FETCH")
            continue

        print(f"\n{ticker} - {summary.get('company_name', 'Unknown')}:")
        print(f"  SIC: {summary.get('sic_code')} ({summary.get('sic_description', '')})")

        # Get most recent fiscal year with debt data
        fiscal_years = summary.get("fiscal_years", {})
        if not fiscal_years:
            print(f"  WARNING: No fiscal year data")
            continue

        most_recent_fy = max(fiscal_years.keys())
        fy_data = fiscal_years[most_recent_fy]
        total_debt = fy_data.get("total_debt")

        if total_debt is None:
            print(f"  PROBLEM: Total debt is MISSING for FY{most_recent_fy}")
            tag_matches = summary.get("tag_matches", {})
            print(f"    ltd_noncurrent tag: {tag_matches.get('ltd_noncurrent', '?')}")
            print(f"    ltd_current tag: {tag_matches.get('ltd_current', '?')}")
            print(f"    debt_combined tag: {tag_matches.get('debt_combined', '?')}")
        elif total_debt == 0:
            print(f"  WARNING: Total debt is $0 for FY{most_recent_fy} - unexpected for debt-heavy company")
        else:
            print(f"  OK: Total debt = ${total_debt/1e9:,.2f}B for FY{most_recent_fy}")
            debt_breakdown = fy_data.get("debt_breakdown")
            if isinstance(debt_breakdown, dict):
                nc = debt_breakdown.get("noncurrent")
                c = debt_breakdown.get("current")
                if nc is not None:
                    print(f"       Noncurrent: ${nc/1e9:,.2f}B")
                if c is not None:
                    print(f"       Current: ${c/1e9:,.2f}B")


def print_recent_ipo_status(all_summaries: dict):
    """Report available history for recent IPO tickers."""
    print(f"\n{'='*100}")
    print("RECENT IPO TICKERS - AVAILABLE HISTORY")
    print("="*100)
    print("\nThese companies have limited filing history; reporting what exists:\n")

    ipo_tickers = ["ARM", "RDDT"]

    for ticker in ipo_tickers:
        summary = all_summaries.get(ticker)
        if summary is None:
            print(f"{ticker}: FAILED TO FETCH (may not be in SEC database yet)")
            continue

        print(f"\n{ticker} - {summary.get('company_name', 'Unknown')}:")
        print(f"  CIK: {summary.get('cik')}")
        print(f"  SIC: {summary.get('sic_code')} ({summary.get('sic_description', '')})")

        fiscal_years = summary.get("fiscal_years", {})
        fy_list = sorted(fiscal_years.keys(), reverse=True)

        print(f"  Fiscal years available: {len(fy_list)}")
        if fy_list:
            print(f"  Years: {', '.join(f'FY{fy}' for fy in fy_list)}")

            # Show data for most recent year
            most_recent = fy_list[0]
            data = fiscal_years[most_recent]
            print(f"  Most recent (FY{most_recent}):")

            def fmt(val):
                if val is None:
                    return "MISSING"
                return f"${val/1e6:,.1f}M"

            print(f"    Revenue: {fmt(data.get('revenue'))}")
            print(f"    Op Income: {fmt(data.get('operating_income'))}")
            print(f"    EBITDA: {fmt(data.get('ebitda_calculated'))}")
        else:
            print(f"  No 10-K filings found yet")


def print_sector_exclusion_summary(all_summaries: dict, ticker_categories: dict):
    """Summarize which tickers should be flagged for sector exclusion."""
    print(f"\n{'='*100}")
    print("SECTOR EXCLUSION SUMMARY")
    print("="*100)
    print("\nTickers that should be flagged for sector-based exclusion:\n")

    exclude_tickers = [t for t, info in ticker_categories.items() if info["category"] == "exclude-sector"]

    for ticker in exclude_tickers:
        summary = all_summaries.get(ticker)
        if summary is None:
            print(f"{ticker}: FAILED TO FETCH")
            continue

        sic = summary.get("sic_code", "?")
        sic_desc = summary.get("sic_description", "Unknown")
        detected_sector = check_sector_exclusion(sic)

        status = "DETECTED" if detected_sector else "NOT DETECTED"
        print(f"  {ticker}: SIC {sic} ({sic_desc})")
        print(f"    Expected: {ticker_categories[ticker]['note']}")
        print(f"    Detection: {status}" + (f" as '{detected_sector}'" if detected_sector else ""))


def run_expanded_test():
    """Run the expanded 20-ticker test with comprehensive analysis."""
    print("="*100)
    print("SEC EDGAR EXPANDED TAG COVERAGE TEST")
    print("20 Tickers Across Multiple Categories")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("="*100)

    # Get credentials
    try:
        sec_user_agent = get_sec_user_agent()
        print(f"\nSEC User-Agent: {sec_user_agent}")
    except ValueError as e:
        print(f"\nERROR: {e}")
        return

    try:
        twelve_data_key = get_twelve_data_api_key()
        print(f"Twelve Data API Key: {twelve_data_key[:4]}...{twelve_data_key[-4:]}")
    except ValueError as e:
        print(f"\nNOTE: {e}")
        print("Proceeding without current price data (not needed for tag coverage test)")
        twelve_data_key = ""

    # List tickers
    tickers = list(TICKER_CATEGORIES.keys())
    print(f"\n{'='*100}")
    print(f"TEST TICKERS ({len(tickers)} total)")
    print("="*100)

    for category in ["large-cap", "mid-cap", "small-cap", "debt-heavy",
                     "exclude-sector", "recent-ipo", "edge-case"]:
        cat_tickers = [t for t, info in TICKER_CATEGORIES.items() if info["category"] == category]
        print(f"\n{category.upper()}:")
        for t in cat_tickers:
            print(f"  {t}: {TICKER_CATEGORIES[t]['note']}")

    # Fetch all tickers
    print(f"\n{'='*100}")
    print("FETCHING DATA (this will take ~2 minutes due to rate limiting)")
    print("="*100)

    all_summaries = {}
    failed_tickers = []

    for i, ticker in enumerate(tickers, 1):
        category = TICKER_CATEGORIES[ticker]["category"]
        print(f"\n[{i:2}/{len(tickers)}] {ticker} ({category})...", end=" ", flush=True)

        try:
            summary = fetch_ticker_data(
                ticker,
                sec_user_agent,
                twelve_data_key,
                verbose=False,
                skip_price=True  # Skip price fetch for bulk test
            )

            if summary:
                all_summaries[ticker] = summary
                fy_count = len(summary.get("fiscal_years", {}))
                sic = summary.get("sic_code", "?")
                print(f"OK (SIC: {sic}, {fy_count} fiscal years)")
            else:
                failed_tickers.append(ticker)
                print("FAILED")
        except Exception as e:
            failed_tickers.append(ticker)
            print(f"ERROR: {e}")

    # Print all analysis reports
    print_summary_table(all_summaries, TICKER_CATEGORIES)

    tag_freq = analyze_tag_frequency(all_summaries)
    print_tag_frequency_table(tag_freq)

    print_completely_missing_concepts(all_summaries, TICKER_CATEGORIES)
    print_debt_heavy_verification(all_summaries)
    print_recent_ipo_status(all_summaries)
    print_sector_exclusion_summary(all_summaries, TICKER_CATEGORIES)

    # Final summary
    print(f"\n{'='*100}")
    print("FINAL SUMMARY")
    print("="*100)
    print(f"\nSuccessfully processed: {len(all_summaries)}/{len(tickers)} tickers")
    if failed_tickers:
        print(f"Failed tickers: {', '.join(failed_tickers)}")

    print(f"\n{'='*100}")
    print("TEST COMPLETE")
    print("="*100)


def main():
    """Main function to test SEC EDGAR + Twelve Data retrieval."""
    print("="*60)
    print("SEC EDGAR + TWELVE DATA RETRIEVAL TEST")
    print("AIO LBO - Data Layer Validation")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("="*60)

    # Get credentials
    try:
        sec_user_agent = get_sec_user_agent()
        print(f"\nSEC User-Agent: {sec_user_agent}")
    except ValueError as e:
        print(f"\nERROR: {e}")
        return

    try:
        twelve_data_key = get_twelve_data_api_key()
        print(f"Twelve Data API Key: {twelve_data_key[:4]}...{twelve_data_key[-4:]}")
    except ValueError as e:
        print(f"\nWARNING: {e}")
        print("Proceeding without current price data...")
        twelve_data_key = None

    # Test tickers:
    # - AAPL: Large cap (should have complete data)
    # - CROX: Mid cap (~$5B, Crocs Inc)
    # - FIZZ: Small cap (~$2B, National Beverage Corp)
    # These test whether SEC has any paywall issues like FMP did
    test_tickers = ["AAPL", "CROX", "FIZZ"]

    print(f"\n{'='*60}")
    print("TEST TICKERS")
    print("="*60)
    print(f"Testing {len(test_tickers)} tickers of different market caps:")
    print("  AAPL - Large cap (Apple Inc)")
    print("  CROX - Mid cap (Crocs Inc, ~$5B market cap)")
    print("  FIZZ - Small cap (National Beverage Corp, ~$2B)")
    print("\nThis tests whether SEC EDGAR restricts data by company size")
    print("(unlike FMP which returned HTTP 402 for smaller companies)")

    all_summaries = {}

    for ticker in test_tickers:
        summary = fetch_ticker_data(
            ticker,
            sec_user_agent,
            twelve_data_key if twelve_data_key else ""
        )

        if summary:
            all_summaries[ticker] = summary
            print_summary(summary)
        else:
            print(f"\n{'!'*60}")
            print(f"FAILED TO FETCH DATA FOR {ticker}")
            print(f"{'!'*60}")

    # Final comparison
    print(f"\n{'='*60}")
    print("DATA COMPLETENESS COMPARISON")
    print("="*60)
    print("\nDoes SEC EDGAR return data for all company sizes?")
    print("-"*60)

    for ticker in test_tickers:
        summary = all_summaries.get(ticker)
        if summary:
            fy_count = len(summary.get("fiscal_years", {}))
            missing_count = len(summary.get("missing_fields", []))
            price_status = "OK" if summary.get("current_price") else "MISSING"
            print(f"  {ticker}:")
            print(f"    - Data retrieved: YES (CIK {summary['cik']})")
            print(f"    - Fiscal years with data: {fy_count}")
            print(f"    - Total missing fields: {missing_count}")
            print(f"    - Current price: {price_status}")
        else:
            print(f"  {ticker}: FAILED TO RETRIEVE")

    print(f"\n{'='*60}")
    print("CONCLUSION")
    print("="*60)
    successful = len(all_summaries)
    print(f"Successfully retrieved data for {successful}/{len(test_tickers)} tickers")

    if successful == len(test_tickers):
        print("\nSEC EDGAR does NOT paywall data by company size.")
        print("All test companies (large, mid, small cap) returned data.")
    else:
        print("\nSome tickers failed - check error messages above.")

    print(f"\n{'='*60}")
    print("TEST COMPLETE")
    print("="*60)


if __name__ == "__main__":
    # Check for test mode argument
    # Usage: python sec_edgar_test.py [email] [api_key] [expanded]
    # Or: python sec_edgar_test.py expanded [email] [api_key]
    run_expanded = False

    for arg in sys.argv[1:]:
        if arg.lower() == "expanded":
            run_expanded = True
            break

    if run_expanded:
        run_expanded_test()
    else:
        main()
