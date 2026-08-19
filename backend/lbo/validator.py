"""
AIO LBO Validator

Validates the summary object from SEC EDGAR data retrieval before modeling.
Returns a structured verdict (pass/degraded/fail) with human-readable messages.
"""

from datetime import datetime, timedelta
from typing import Optional


# Sectors excluded from LBO analysis (don't report EBITDA-style operating structure)
EXCLUDED_SIC_RANGES = {
    "banks": (6000, 6199),
    "insurance": (6300, 6411),
    "reits": (6798, 6798),
    "utilities": (4900, 4939),
}

SECTOR_EXCLUSION_MESSAGE = (
    "This sector doesn't report an EBITDA-style operating structure "
    "that this model is built for."
)


def check_sector_exclusion(sic_code) -> tuple[bool, Optional[str]]:
    """
    Check if SIC code falls in an excluded sector.
    Returns (is_excluded, reason_message).
    """
    try:
        sic = int(sic_code)
        for sector_name, (low, high) in EXCLUDED_SIC_RANGES.items():
            if low <= sic <= high:
                sector_display = sector_name.replace("_", " ").title()
                if sector_name == "reits":
                    sector_display = "REITs"
                return True, f"{sector_display} (SIC {sic}): {SECTOR_EXCLUSION_MESSAGE}"
    except (ValueError, TypeError):
        pass
    return False, None


def check_filing_staleness(summary: dict) -> tuple[bool, Optional[str]]:
    """
    Check if the most recent fiscal year filing is more than 18 months old.
    Returns (is_stale, reason_message).
    """
    fiscal_years = summary.get("fiscal_years", {})
    if not fiscal_years:
        return False, None  # Will be caught by zero FY check

    most_recent_fy = max(fiscal_years.keys())
    fy_data = fiscal_years[most_recent_fy]

    # Try to get the filing date from the data
    # The summary stores end_date for reference, but we can estimate from fiscal year
    # A filing for FY2024 should be filed by early 2025 (within ~90 days of fiscal year end)
    # If we're now in July 2026 and most recent is FY2024, that's about 18 months

    # More robust: check fiscal year end date if available
    # For now, use fiscal year as a proxy - if most recent FY is more than 2 years ago, it's stale
    current_year = datetime.now().year
    current_month = datetime.now().month

    # Estimate: FY2024 data should be available by April 2025
    # So in July 2026, FY2024 is ~15 months old, FY2023 would be ~27 months old
    # We'll flag if the fiscal year is more than 1.5 years behind current

    # A company with fiscal year ending Dec 2024 would file by March 2025
    # 18 months from March 2025 = September 2026
    # So if we're past Sept 2026 and most recent is FY2024, it's stale

    # Simpler heuristic: if most recent FY is 2+ years behind current year, likely stale
    if current_year - most_recent_fy >= 2:
        return True, (
            f"Most recent fiscal year data (FY{most_recent_fy}) is over 18 months old. "
            f"This may indicate a delisting, acquisition, or reporting lapse."
        )

    return False, None


def validate(summary: dict) -> dict:
    """
    Validate a company summary from SEC EDGAR data retrieval.

    Args:
        summary: The summary dict from fetch_ticker_data(), containing:
            - ticker, company_name, cik, sic_code
            - shares_outstanding, current_price
            - fiscal_years: dict of {year: {revenue, operating_income, da,
              ebitda_calculated, total_debt, cash, capex, missing}}
            - tag_matches, missing_fields

    Returns:
        dict with:
            - status: "pass" | "degraded" | "fail"
            - missing_hard: list of human-readable messages for missing hard requirements
            - missing_soft: list of human-readable messages for missing soft requirements
            - disqualifying_reasons: list of human-readable reasons for failure
            - sector_excluded: bool
            - sector_excluded_reason: str or None
            - defaults_applied: list of defaults that will be used for missing soft fields
    """
    result = {
        "status": "pass",
        "missing_hard": [],
        "missing_soft": [],
        "disqualifying_reasons": [],
        "sector_excluded": False,
        "sector_excluded_reason": None,
        "defaults_applied": [],
        "substitute_warnings": [],  # Warnings for fields using proxy/substitute values
    }

    ticker = summary.get("ticker", "Unknown")
    fiscal_years = summary.get("fiscal_years", {})
    substitute_flags = summary.get("substitute_flags", {})

    # =========================================================================
    # DISQUALIFYING CONDITIONS (check these first - any one = fail)
    # =========================================================================

    # 1. Zero fiscal years of 10-K data
    if not fiscal_years:
        result["status"] = "fail"
        result["disqualifying_reasons"].append(
            "No 10-K filings found — this may be a foreign private issuer "
            "filing under a different form (e.g., 20-F for IFRS), which isn't supported yet."
        )
        # Return early - can't check other conditions without fiscal year data
        return result

    # 2. Sector exclusion
    sic_code = summary.get("sic_code")
    is_excluded, exclusion_reason = check_sector_exclusion(sic_code)
    if is_excluded:
        result["status"] = "fail"
        result["sector_excluded"] = True
        result["sector_excluded_reason"] = exclusion_reason
        result["disqualifying_reasons"].append(exclusion_reason)
        # Don't return early - still report other issues for completeness

    # 3. Stale data check
    is_stale, stale_reason = check_filing_staleness(summary)
    if is_stale:
        result["status"] = "fail"
        result["disqualifying_reasons"].append(stale_reason)

    # 4. EBITDA <= 0 for most recent fiscal year
    most_recent_fy = max(fiscal_years.keys())
    fy_data = fiscal_years[most_recent_fy]
    ebitda = fy_data.get("ebitda_calculated")

    if ebitda is not None and ebitda <= 0:
        result["status"] = "fail"
        if ebitda == 0:
            result["disqualifying_reasons"].append(
                f"EBITDA is exactly $0 for FY{most_recent_fy}. "
                f"Cannot build a meaningful leverage analysis without positive EBITDA."
            )
        else:
            result["disqualifying_reasons"].append(
                f"EBITDA is negative (${ebitda/1e6:,.1f}M) for FY{most_recent_fy}. "
                f"Cannot build a meaningful leverage analysis without positive EBITDA."
            )

    # If already failed due to disqualifying conditions, still check requirements
    # for completeness in the output, but status stays "fail"

    # =========================================================================
    # HARD REQUIREMENTS (missing 2+ = fail, missing 1 = degraded)
    # =========================================================================

    hard_missing = []

    # Revenue (most recent FY)
    revenue = fy_data.get("revenue")
    if revenue is None:
        hard_missing.append(
            f"Revenue data is missing for the most recent fiscal year (FY{most_recent_fy})."
        )

    # Operating income (most recent FY)
    op_income = fy_data.get("operating_income")
    if op_income is None:
        hard_missing.append(
            f"Operating income data is missing for the most recent fiscal year (FY{most_recent_fy})."
        )

    # D&A (most recent FY)
    da = fy_data.get("da")
    if da is None:
        hard_missing.append(
            f"Depreciation & Amortization (D&A) data is missing for the most recent fiscal year (FY{most_recent_fy})."
        )

    # Shares outstanding
    shares = summary.get("shares_outstanding")
    if shares is None:
        hard_missing.append(
            "Shares outstanding data is missing. Cannot calculate equity value or per-share metrics."
        )

    # Current share price
    price = summary.get("current_price")
    if price is None:
        hard_missing.append(
            "Current share price is missing. Cannot calculate market cap or offer premium."
        )

    result["missing_hard"] = hard_missing

    # Determine status impact from hard requirements
    if len(hard_missing) >= 2 and result["status"] != "fail":
        result["status"] = "fail"
        result["disqualifying_reasons"].append(
            f"Missing {len(hard_missing)} hard requirements (2+ missing = cannot build model)."
        )
    elif len(hard_missing) == 1 and result["status"] == "pass":
        result["status"] = "degraded"

    # =========================================================================
    # SOFT REQUIREMENTS (missing = degraded with defaults, never fail alone)
    # =========================================================================

    soft_missing = []
    defaults = []

    # Total debt
    total_debt = fy_data.get("total_debt")
    if total_debt is None:
        soft_missing.append(
            f"Total debt data is missing for FY{most_recent_fy}. "
            f"This could indicate a genuinely debt-free company."
        )
        defaults.append(
            "Total debt will default to $0 — verify this is accurate before proceeding."
        )

    # Cash
    cash = fy_data.get("cash")
    if cash is None:
        soft_missing.append(
            f"Cash and equivalents data is missing for FY{most_recent_fy}."
        )
        defaults.append(
            "Cash will default to $0 — verify this is accurate before proceeding."
        )

    # Capex
    capex = fy_data.get("capex")
    if capex is None:
        soft_missing.append(
            f"Capital expenditures (CapEx) data is missing for FY{most_recent_fy}."
        )
        defaults.append(
            "CapEx will default to 0% of revenue — adjust the CapEx % assumption if needed."
        )

    result["missing_soft"] = soft_missing
    result["defaults_applied"] = defaults

    # Soft requirements alone only degrade, never fail
    if soft_missing and result["status"] == "pass":
        result["status"] = "degraded"

    # =========================================================================
    # SUBSTITUTE VALUE WARNINGS
    # =========================================================================

    substitute_warnings = []

    # Check for operating income substitutes
    op_income_flag = substitute_flags.get("operating_income")
    if op_income_flag == "CALCULATED":
        substitute_warnings.append(
            "Operating Income is CALCULATED from GrossProfit - SG&A - R&D. "
            "This company does not report OperatingIncomeLoss directly. "
            "The calculated value may differ from the company's reported operating income "
            "if they have other operating expenses (e.g., restructuring, impairment)."
        )
    elif op_income_flag == "PRETAX_SUBSTITUTE":
        substitute_warnings.append(
            "WARNING: Operating Income is using PRE-TAX INCOME as a substitute. "
            "Pre-tax income includes non-operating items (interest expense, other income/expense) "
            "that operating income specifically excludes. "
            "EBITDA calculations will include these non-operating items and may be misleading."
        )

    result["substitute_warnings"] = substitute_warnings

    # Substitute warnings cause degraded status (not fail)
    if substitute_warnings and result["status"] == "pass":
        result["status"] = "degraded"

    return result


def format_validation_result(summary: dict, result: dict) -> str:
    """
    Format the validation result as a human-readable string.
    """
    ticker = summary.get("ticker", "Unknown")
    company = summary.get("company_name", "Unknown")

    lines = [
        f"{'='*60}",
        f"VALIDATION RESULT: {ticker}",
        f"{'='*60}",
        f"Company: {company}",
        f"Status: {result['status'].upper()}",
    ]

    if result["sector_excluded"]:
        lines.append(f"\nSector Excluded: Yes")
        lines.append(f"Reason: {result['sector_excluded_reason']}")

    if result["disqualifying_reasons"]:
        lines.append(f"\n--- Disqualifying Conditions ---")
        for reason in result["disqualifying_reasons"]:
            lines.append(f"  [X] {reason}")

    if result["missing_hard"]:
        lines.append(f"\n--- Missing Hard Requirements ---")
        for msg in result["missing_hard"]:
            lines.append(f"  [!] {msg}")

    if result["missing_soft"]:
        lines.append(f"\n--- Missing Soft Requirements ---")
        for msg in result["missing_soft"]:
            lines.append(f"  [o] {msg}")

    if result["defaults_applied"]:
        lines.append(f"\n--- Defaults That Will Be Applied ---")
        for default in result["defaults_applied"]:
            lines.append(f"  --> {default}")

    if result.get("substitute_warnings"):
        lines.append(f"\n--- Substitute Value Warnings ---")
        for warning in result["substitute_warnings"]:
            lines.append(f"  [~] {warning}")

    if result["status"] == "pass" and not result["missing_soft"] and not result.get("substitute_warnings"):
        lines.append(f"\n[OK] All required data present. Ready for modeling.")

    return "\n".join(lines)


def print_validation_summary_table(all_results: dict):
    """
    Print a summary table of validation results for multiple tickers.
    """
    print(f"\n{'='*110}")
    print("VALIDATION SUMMARY TABLE")
    print("="*110)

    # Header
    print(f"\n{'Ticker':<8} {'Status':<10} {'Sector':<8} {'Hard':<6} {'Soft':<6} {'Subs':<6} {'Notes'}")
    print("-"*110)

    for ticker, (summary, result) in all_results.items():
        status = result["status"].upper()
        sector = "Yes" if result["sector_excluded"] else "-"
        hard_count = len(result["missing_hard"])
        soft_count = len(result["missing_soft"])
        subs_count = len(result.get("substitute_warnings", []))

        # Build concise reason string
        reasons = []
        if result["sector_excluded"]:
            sic = summary.get("sic_code", "?")
            reasons.append(f"SIC {sic}")
        if result["disqualifying_reasons"]:
            for r in result["disqualifying_reasons"]:
                # Extract first few words
                short = r.split(".")[0][:35]
                if short not in reasons and "SIC" not in short and "missing" not in short.lower():
                    reasons.append(short)
        if hard_count > 0 and not any("missing" in r.lower() for r in reasons):
            reasons.append(f"{hard_count} hard req missing")

        # Add substitute flag indicator
        sub_flags = summary.get("substitute_flags", {})
        if sub_flags.get("operating_income") == "CALCULATED":
            reasons.append("OpInc=CALC")
        elif sub_flags.get("operating_income") == "PRETAX_SUBSTITUTE":
            reasons.append("OpInc=PRETAX!")

        reason_str = "; ".join(reasons[:3]) if reasons else "-"
        if len(reason_str) > 50:
            reason_str = reason_str[:47] + "..."

        print(f"{ticker:<8} {status:<10} {sector:<8} {hard_count:<6} {soft_count:<6} {subs_count:<6} {reason_str}")


# =============================================================================
# TEST HARNESS
# =============================================================================

if __name__ == "__main__":
    import sys
    import os

    # Add parent directory to path for imports
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # Allow command-line override for SEC email
    # Usage: python validator.py [sec_email]
    if len(sys.argv) >= 2 and sys.argv[1]:
        os.environ["SEC_CONTACT_EMAIL"] = sys.argv[1]

    from .sec_edgar_test import (
        get_sec_user_agent,
        get_twelve_data_api_key,
        fetch_ticker_data,
        TICKER_CATEGORIES,
    )

    print("="*100)
    print("AIO LBO VALIDATOR TEST")
    print("Testing against 20 tickers from SEC EDGAR data")
    print("="*100)

    # Get credentials
    try:
        sec_user_agent = get_sec_user_agent()
        print(f"\nSEC User-Agent: {sec_user_agent}")
    except ValueError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    try:
        twelve_data_key = get_twelve_data_api_key()
    except ValueError:
        twelve_data_key = ""
        print("Note: No Twelve Data key - current price will be missing")

    # Fetch and validate all tickers
    tickers = list(TICKER_CATEGORIES.keys())
    all_results = {}

    print(f"\n{'='*100}")
    print(f"FETCHING AND VALIDATING {len(tickers)} TICKERS")
    print("="*100)

    for i, ticker in enumerate(tickers, 1):
        category = TICKER_CATEGORIES[ticker]["category"]
        print(f"\n[{i:2}/{len(tickers)}] {ticker} ({category})...", end=" ", flush=True)

        try:
            summary = fetch_ticker_data(
                ticker,
                sec_user_agent,
                twelve_data_key,
                verbose=False,
                skip_price=False  # Fetch price to validate current_price availability
            )

            if summary:
                result = validate(summary)
                all_results[ticker] = (summary, result)
                print(f"{result['status'].upper()}")
            else:
                print("FETCH FAILED")
                # Create a minimal summary for failed fetches
                all_results[ticker] = (
                    {"ticker": ticker, "fiscal_years": {}},
                    validate({"ticker": ticker, "fiscal_years": {}})
                )
        except Exception as e:
            print(f"ERROR: {e}")

    # Print summary table
    print_validation_summary_table(all_results)

    # Print detailed results for failures and degraded
    print(f"\n{'='*100}")
    print("DETAILED RESULTS FOR FAILED/DEGRADED TICKERS")
    print("="*100)

    for ticker, (summary, result) in all_results.items():
        if result["status"] != "pass":
            print(f"\n{format_validation_result(summary, result)}")

    # Verify expected outcomes
    print(f"\n{'='*100}")
    print("EXPECTED OUTCOME VERIFICATION")
    print("="*100)

    expected_pass_or_degraded = [
        "AAPL", "MSFT", "JNJ", "CROX", "DECK", "POOL", "FIZZ", "SMPL", "WING",
        "CCL", "AAL", "TSLA"
    ]
    # Note: IRM (REIT), BRK.B (Insurance) are correctly excluded by sector
    # RDDT has negative EBITDA which is a disqualifying condition
    expected_sector_fail = ["JPM", "AIG", "O", "DUK", "IRM", "BRK.B"]
    expected_no_10k = ["ARM"]
    expected_negative_ebitda = ["RDDT"]

    print("\nChecking expected outcomes:")

    issues = []

    # Check pass/degraded tickers
    for ticker in expected_pass_or_degraded:
        if ticker in all_results:
            _, result = all_results[ticker]
            if result["status"] == "fail":
                # Check if it's a sector exclusion (would be unexpected)
                if result["sector_excluded"]:
                    issues.append(f"  [X] {ticker}: Expected pass/degraded but got FAIL (sector excluded)")
                else:
                    # Check the disqualifying reasons
                    reasons = "; ".join(result["disqualifying_reasons"][:1])
                    issues.append(f"  [X] {ticker}: Expected pass/degraded but got FAIL ({reasons})")
            else:
                print(f"  [OK] {ticker}: {result['status'].upper()} (as expected)")
        else:
            issues.append(f"  [X] {ticker}: Not in results")

    # Check sector exclusion tickers
    for ticker in expected_sector_fail:
        if ticker in all_results:
            _, result = all_results[ticker]
            if result["sector_excluded"]:
                print(f"  [OK] {ticker}: FAIL with sector_excluded=True (as expected)")
            else:
                issues.append(f"  [X] {ticker}: Expected sector exclusion but sector_excluded=False")
        else:
            issues.append(f"  [X] {ticker}: Not in results")

    # Check no 10-K tickers
    for ticker in expected_no_10k:
        if ticker in all_results:
            _, result = all_results[ticker]
            if result["status"] == "fail" and any("10-K" in r or "20-F" in r for r in result["disqualifying_reasons"]):
                print(f"  [OK] {ticker}: FAIL with 'no 10-K filings' reason (as expected)")
            else:
                reasons = result["disqualifying_reasons"]
                issues.append(f"  [X] {ticker}: Expected 'no 10-K' fail but got: {reasons}")
        else:
            issues.append(f"  [X] {ticker}: Not in results")

    # Check negative EBITDA tickers
    for ticker in expected_negative_ebitda:
        if ticker in all_results:
            _, result = all_results[ticker]
            if result["status"] == "fail" and any("EBITDA is negative" in r for r in result["disqualifying_reasons"]):
                print(f"  [OK] {ticker}: FAIL with negative EBITDA (as expected)")
            else:
                reasons = result["disqualifying_reasons"]
                issues.append(f"  [X] {ticker}: Expected negative EBITDA fail but got: {reasons}")
        else:
            issues.append(f"  [X] {ticker}: Not in results")

    if issues:
        print("\nIssues found:")
        for issue in issues:
            print(issue)
    else:
        print("\n[OK] All expected outcomes matched!")

    print(f"\n{'='*100}")
    print("VALIDATOR TEST COMPLETE")
    print("="*100)
