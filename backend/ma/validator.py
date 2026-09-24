"""
M&A Modeling Tool - Validator

Validates the two-company pair object from the Phase 1 data layer before
modeling. Applied independently to BOTH the Acquirer and the Target, then
combined into one overall verdict.

Verdict shape carries over from AIO LBO's validator (see
/reference/backend/validator.py): {"status": "pass"|"degraded"|"fail",
"missing_hard": [...], "missing_soft": [...], "disqualifying_reasons": [...],
...} — extended here to per-company sub-verdicts plus a combined verdict.

DELIBERATE DIVERGENCE FROM AIO LBO: negative/zero EBITDA or Net Income is
NOT disqualifying here. An LBO needs a positive leverage denominator; an
M&A accretion/dilution model works fine on a loss-making company (arguably
a more interesting deal to model). Negative Net Income produces a WARNING
and degraded status at most — never a hard fail.
"""

from datetime import datetime
from typing import Optional


# Sectors excluded from analysis (don't report an EBITDA-style operating
# structure) — applies to EITHER company in the pair. Carried over from AIO LBO.
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


def check_sector_exclusion(sic_code) -> tuple:
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


def check_filing_staleness(profile: dict) -> tuple:
    """
    Check if the most recent fiscal year filing is stale (2+ years behind).
    Returns (is_stale, reason_message). Carried over from AIO LBO.
    """
    fiscal_years = profile.get("fiscal_years", {})
    if not fiscal_years:
        return False, None  # Caught by the zero-FY check

    most_recent_fy = max(fiscal_years.keys())
    current_year = datetime.now().year

    if current_year - most_recent_fy >= 2:
        return True, (
            f"Most recent fiscal year data (FY{most_recent_fy}) is over 18 months old. "
            f"This may indicate a delisting, acquisition, or reporting lapse."
        )

    return False, None


def validate_company(profile: Optional[dict], role: str = "company",
                      fetch_error: Optional[str] = None) -> dict:
    """
    Validate one company profile from the Phase 1 data layer.

    Args:
        profile: A company profile dict from fetch_ma_pair()["acquirer"|"target"],
                 or None if the fetch failed entirely.
        role: "acquirer" or "target" (used in messages only).

    Returns the AIO LBO-shaped verdict dict:
        - status: "pass" | "degraded" | "fail"
        - missing_hard / missing_soft / disqualifying_reasons
        - sector_excluded / sector_excluded_reason
        - defaults_applied
        - substitute_warnings
        - warnings (M&A addition: non-fatal flags, e.g. negative net income)
        - goodwill_precision_degraded (M&A addition: True when Total
          Assets/Liabilities are missing so PPA book-equity/Goodwill must be
          handled gracefully downstream instead of computed precisely)
    """
    result = {
        "role": role,
        "ticker": (profile or {}).get("ticker", "Unknown"),
        "status": "pass",
        "missing_hard": [],
        "missing_soft": [],
        "disqualifying_reasons": [],
        "sector_excluded": False,
        "sector_excluded_reason": None,
        "defaults_applied": [],
        "substitute_warnings": [],
        "warnings": [],
        "goodwill_precision_degraded": False,
    }

    if profile is None:
        result["status"] = "fail"
        if fetch_error:
            # A distinct backend-side failure (e.g. SEC EDGAR rate-limiting
            # the company_tickers.json mapping fetch) — NOT a "ticker not
            # found" situation, so don't say so.
            result["disqualifying_reasons"].append(fetch_error)
        else:
            result["disqualifying_reasons"].append(
                f"No data could be fetched for the {role} — ticker not found or "
                f"SEC EDGAR returned no usable filings."
            )
        return result

    fiscal_years = profile.get("fiscal_years", {})
    substitute_flags = profile.get("substitute_flags", {})

    # =========================================================================
    # DISQUALIFYING CONDITIONS (carried over from AIO LBO — any one = fail)
    # NOTE: negative EBITDA / Net Income is deliberately NOT in this list.
    # =========================================================================

    # 1. Zero fiscal years of 10-K data
    if not fiscal_years:
        result["status"] = "fail"
        result["disqualifying_reasons"].append(
            "No 10-K filings found — this may be a foreign private issuer "
            "filing under a different form (e.g., 20-F for IFRS), which isn't supported yet."
        )
        return result

    # 2. Sector exclusion
    sic_code = profile.get("sic_code")
    is_excluded, exclusion_reason = check_sector_exclusion(sic_code)
    if is_excluded:
        result["status"] = "fail"
        result["sector_excluded"] = True
        result["sector_excluded_reason"] = exclusion_reason
        result["disqualifying_reasons"].append(exclusion_reason)

    # 3. Stale data check
    is_stale, stale_reason = check_filing_staleness(profile)
    if is_stale:
        result["status"] = "fail"
        result["disqualifying_reasons"].append(stale_reason)

    most_recent_fy = max(fiscal_years.keys())
    fy_data = fiscal_years[most_recent_fy]

    # =========================================================================
    # HARD REQUIREMENTS (missing 2+ = fail, missing exactly 1 = degraded)
    # =========================================================================

    hard_missing = []

    if fy_data.get("revenue") is None:
        hard_missing.append(
            f"Revenue data is missing for the most recent fiscal year (FY{most_recent_fy})."
        )

    if fy_data.get("operating_income") is None:
        hard_missing.append(
            f"Operating income data is missing for the most recent fiscal year (FY{most_recent_fy})."
        )

    if fy_data.get("da") is None:
        hard_missing.append(
            f"Depreciation & Amortization (D&A) data is missing for the most recent fiscal year (FY{most_recent_fy})."
        )

    if fy_data.get("net_income") is None:
        hard_missing.append(
            f"Net income data is missing for the most recent fiscal year (FY{most_recent_fy})."
        )

    # Per-share figures: need Diluted EPS OR a share count (diluted preferred,
    # basic point-in-time acceptable) — at least one route to per-share math.
    has_eps = fy_data.get("diluted_eps") is not None
    has_share_count = (
        fy_data.get("diluted_shares") is not None
        or profile.get("diluted_shares") is not None
        or profile.get("shares_outstanding") is not None
    )
    if not has_eps and not has_share_count:
        hard_missing.append(
            "Neither diluted EPS nor any share count is available. "
            "Cannot derive per-share figures for accretion/dilution."
        )

    if profile.get("current_price") is None:
        hard_missing.append(
            "Current share price is missing. Cannot calculate market cap or offer premium."
        )

    result["missing_hard"] = hard_missing

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

    if fy_data.get("total_debt") is None:
        soft_missing.append(
            f"Total debt data is missing for FY{most_recent_fy}. "
            f"This could indicate a genuinely debt-free company."
        )
        defaults.append(
            "Total debt will default to $0 — verify this is accurate before proceeding."
        )

    if fy_data.get("cash") is None:
        soft_missing.append(
            f"Cash and equivalents data is missing for FY{most_recent_fy}."
        )
        defaults.append(
            "Cash will default to $0 — verify this is accurate before proceeding."
        )

    if fy_data.get("capex") is None:
        soft_missing.append(
            f"Capital expenditures (CapEx) data is missing for FY{most_recent_fy}."
        )
        defaults.append(
            "CapEx will default to 0% of revenue — adjust the CapEx % assumption if needed."
        )

    # M&A-specific soft requirement: Total Assets / Liabilities feed the
    # Purchase Price Allocation book-equity calculation. Missing values
    # degrade Goodwill precision downstream — they must not block the model.
    assets_missing = fy_data.get("total_assets") is None
    liab_missing = fy_data.get("total_liabilities") is None
    if assets_missing or liab_missing:
        which = []
        if assets_missing:
            which.append("Total Assets")
        if liab_missing:
            which.append("Total Liabilities")
        soft_missing.append(
            f"{' and '.join(which)} missing for FY{most_recent_fy}. "
            f"Book equity for Purchase Price Allocation cannot be computed precisely."
        )
        defaults.append(
            "Goodwill will be reported as approximate (book equity unavailable) — "
            "downstream phases must handle this gracefully, not crash."
        )
        result["goodwill_precision_degraded"] = True

    result["missing_soft"] = soft_missing
    result["defaults_applied"] = defaults

    if soft_missing and result["status"] == "pass":
        result["status"] = "degraded"

    # =========================================================================
    # WARNINGS (M&A divergence: negative earnings are analyzable, not fatal)
    # =========================================================================

    warnings = []

    net_income = fy_data.get("net_income")
    if net_income is not None and net_income <= 0:
        warnings.append(
            f"Net income is {'zero' if net_income == 0 else 'negative'} "
            f"(${net_income/1e6:,.1f}M) for FY{most_recent_fy}. The accretion/"
            f"dilution math still works — interpret EPS impact with care for a "
            f"loss-making {role}."
        )

    ebitda = fy_data.get("ebitda_calculated")
    if ebitda is not None and ebitda <= 0:
        warnings.append(
            f"EBITDA is non-positive (${ebitda/1e6:,.1f}M) for FY{most_recent_fy}. "
            f"Unlike an LBO, this does not block an M&A model, but multiples "
            f"based on EBITDA will not be meaningful."
        )

    result["warnings"] = warnings

    if warnings and result["status"] == "pass":
        result["status"] = "degraded"

    # =========================================================================
    # SUBSTITUTE VALUE WARNINGS (carried over from AIO LBO, plus M&A flags)
    # =========================================================================

    substitute_warnings = []

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

    if substitute_flags.get("total_liabilities") == "CALCULATED":
        substitute_warnings.append(
            "Total Liabilities is CALCULATED as LiabilitiesAndStockholdersEquity "
            "minus StockholdersEquity (no direct Liabilities tag filed). "
            "Values are arithmetically exact but derived."
        )

    if substitute_flags.get("diluted_eps") == "BASIC_SUBSTITUTE":
        substitute_warnings.append(
            "Diluted EPS is using BASIC EPS as a substitute (no diluted tag filed; "
            "company likely has no dilutive instruments)."
        )

    if substitute_flags.get("diluted_shares") == "BASIC_SUBSTITUTE":
        substitute_warnings.append(
            "Diluted share count is using basic weighted-average shares as a "
            "substitute (no diluted tag filed)."
        )

    result["substitute_warnings"] = substitute_warnings

    if substitute_warnings and result["status"] == "pass":
        result["status"] = "degraded"

    return result


def validate_pair(pair: dict) -> dict:
    """
    Validate a two-company fetch result from fetch_ma_pair().

    Returns:
        {
            "status": "pass" | "degraded" | "fail",   # combined verdict
            "disqualifying_reasons": [...],            # pair-level, prefixed
            "acquirer": {per-company verdict},
            "target": {per-company verdict},
        }

    Combined rules:
    - Either company failing (including sector exclusion of EITHER company,
      in either position) fails the pair.
    - Otherwise either company degraded degrades the pair.
    """
    fetch_errors = pair.get("fetch_errors", {})
    acq_verdict = validate_company(pair.get("acquirer"), role="acquirer",
                                    fetch_error=fetch_errors.get("acquirer"))
    tgt_verdict = validate_company(pair.get("target"), role="target",
                                    fetch_error=fetch_errors.get("target"))

    combined_reasons = []
    for verdict in (acq_verdict, tgt_verdict):
        label = f"{verdict['role'].upper()} {verdict['ticker']}"
        for reason in verdict["disqualifying_reasons"]:
            combined_reasons.append(f"[{label}] {reason}")

    statuses = {acq_verdict["status"], tgt_verdict["status"]}
    if "fail" in statuses:
        combined_status = "fail"
    elif "degraded" in statuses:
        combined_status = "degraded"
    else:
        combined_status = "pass"

    return {
        "status": combined_status,
        "disqualifying_reasons": combined_reasons,
        "acquirer": acq_verdict,
        "target": tgt_verdict,
    }


def format_pair_validation(pair_verdict: dict) -> str:
    """Format a pair validation verdict as a human-readable string."""
    lines = [
        f"{'='*60}",
        f"PAIR VALIDATION: "
        f"{pair_verdict['acquirer']['ticker']} (acquirer) + "
        f"{pair_verdict['target']['ticker']} (target)",
        f"{'='*60}",
        f"Combined Status: {pair_verdict['status'].upper()}",
    ]

    if pair_verdict["disqualifying_reasons"]:
        lines.append("\n--- Disqualifying Conditions (pair) ---")
        for reason in pair_verdict["disqualifying_reasons"]:
            lines.append(f"  [X] {reason}")

    for role in ("acquirer", "target"):
        v = pair_verdict[role]
        lines.append(f"\n--- {role.upper()}: {v['ticker']} — {v['status'].upper()} ---")
        for msg in v["missing_hard"]:
            lines.append(f"  [!] {msg}")
        for msg in v["missing_soft"]:
            lines.append(f"  [o] {msg}")
        for msg in v["defaults_applied"]:
            lines.append(f"  --> {msg}")
        for msg in v["warnings"]:
            lines.append(f"  [w] {msg}")
        for msg in v["substitute_warnings"]:
            lines.append(f"  [~] {msg}")
        if v["status"] == "pass":
            lines.append("  [OK] All required data present.")

    return "\n".join(lines)
