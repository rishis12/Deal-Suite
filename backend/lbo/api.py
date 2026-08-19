"""
AIO LBO FastAPI Backend

Provides REST API endpoints for the LBO analysis tool:
- POST /analyze - Fetch and validate ticker data
- POST /generate - Generate Excel model and narrative report
- POST /compare - Compare two models
"""

import base64
import os
import shutil
import tempfile
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Import existing modules (relative — this app is mounted as the `lbo` package)
from .sec_edgar_test import fetch_ticker_data
from .validator import validate
from .excel_generator import generate_workbook, calculate_revenue_growth_rate
from .report_generator import (
    recalculate_workbook,
    extract_data_from_workbook,
    compute_feasibility_score,
    generate_narrative,
    LLMProviderError,
)
from .comparison_tool import (
    compare_files,
    build_scenario_comparison_prompt,
    build_company_comparison_prompt,
    generate_comparison_commentary,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

# No hardcoded fallbacks in Deal Suite — configure via env vars only
# (SEC_CONTACT_EMAIL, TWELVE_DATA_API_KEY). Keys never live in this repo.
_FALLBACK_SEC_EMAIL = ""
_FALLBACK_TWELVE_KEY = ""

def _get_env_with_fallback(env_name: str, fallback: str) -> str:
    """Get env var, but use fallback if value looks like a command argument."""
    value = os.environ.get(env_name, "")
    # Detect corrupted env vars (contain ":" like "api:app" or start with "--")
    if not value or ":" in value or value.startswith("--") or value.startswith("0."):
        print(f"[CONFIG] {env_name} corrupted ('{value}'), using fallback")
        return fallback
    return value

SEC_CONTACT_EMAIL = _get_env_with_fallback("SEC_CONTACT_EMAIL", _FALLBACK_SEC_EMAIL)
# SEC requires User-Agent format: "AppName contact@email.com"
SEC_USER_AGENT = f"AIO-LBO-Tool {SEC_CONTACT_EMAIL}"
TWELVE_DATA_API_KEY = _get_env_with_fallback("TWELVE_DATA_API_KEY", _FALLBACK_TWELVE_KEY)

# Startup diagnostics
print(f"[STARTUP] === CONFIGURATION ===")
print(f"[STARTUP] SEC_CONTACT_EMAIL: '{SEC_CONTACT_EMAIL}'")
print(f"[STARTUP] SEC_USER_AGENT: '{SEC_USER_AGENT}'")
print(f"[STARTUP] TWELVE_DATA_API_KEY: '{TWELVE_DATA_API_KEY[:8]}...' (truncated)")

# CORS: Set FRONTEND_URL in production to lock down to your frontend domain
# e.g., FRONTEND_URL=https://your-app.vercel.app
# For multiple origins, use comma-separated: https://app1.com,https://app2.com
# Defaults to "*" (allow all) for local development
FRONTEND_URL = os.environ.get("FRONTEND_URL", "")

# Rate limiting for /analyze (protects shared Twelve Data quota)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX_REQUESTS = 10  # per IP per window

# Request timeout (seconds)
REQUEST_TIMEOUT = 120


# =============================================================================
# RATE LIMITING
# =============================================================================

@dataclass
class RateLimitEntry:
    timestamps: list

rate_limit_store: Dict[str, RateLimitEntry] = defaultdict(lambda: RateLimitEntry(timestamps=[]))


def check_rate_limit(client_ip: str) -> bool:
    """Check if client is within rate limit. Returns True if allowed."""
    now = time.time()
    entry = rate_limit_store[client_ip]

    # Remove old timestamps
    entry.timestamps = [t for t in entry.timestamps if now - t < RATE_LIMIT_WINDOW]

    if len(entry.timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        return False

    entry.timestamps.append(now)
    return True


# =============================================================================
# PYDANTIC MODELS (matching types.ts with camelCase)
# =============================================================================

class AnalyzeRequest(BaseModel):
    ticker: str


class UserOverrides(BaseModel):
    """User-provided overrides for missing data fields."""
    currentPrice: Optional[float] = None
    totalDebt: Optional[float] = None
    cash: Optional[float] = None
    capex: Optional[float] = None


class GenerateRequest(BaseModel):
    ticker: str
    assumptions: Dict[str, Any]
    userOverrides: Optional[UserOverrides] = None
    llmProvider: Optional[str] = None
    llmApiKey: Optional[str] = None


class RevenuePoint(BaseModel):
    year: int
    revenue: float


class ValidationResult(BaseModel):
    status: str
    missingHard: List[str]
    missingSoft: List[str]
    disqualifyingReasons: List[str]
    sectorExcluded: bool
    sectorExcludedReason: Optional[str]
    defaultsApplied: List[str]
    substituteWarnings: List[str]


class CompanySnapshot(BaseModel):
    ticker: str
    companyName: str
    sicCode: int
    sicDescription: str
    currentPrice: float
    sharesOutstanding: float
    marketCap: float
    revenueHistory: List[RevenuePoint]
    validation: ValidationResult


class AssumptionMeta(BaseModel):
    key: str
    label: str
    group: str
    format: str
    source: str
    flag: Optional[str]


class ScoreBreakdownMax(BaseModel):
    irr: int = 30
    moic: int = 20
    debtService: int = 25
    leverageReduction: int = 15
    dataQuality: int = 10


class ScoreBreakdown(BaseModel):
    total: float
    irr: float
    moic: float
    debtService: float
    leverageReduction: float
    dataQuality: float
    max: ScoreBreakdownMax


class SensitivityCell(BaseModel):
    entryMultiple: float
    exitMultiple: float
    moic: float
    irr: float
    isBase: bool


class ModelResults(BaseModel):
    irr: float
    moic: float
    feasibility: ScoreBreakdown
    exitEquityValue: float
    reportMarkdown: str


class ComparisonDelta(BaseModel):
    metric: str
    valueA: str
    valueB: str
    change: str


class ComparisonResultResponse(BaseModel):
    mode: str
    deltas: List[ComparisonDelta]
    commentary: Optional[str]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def build_validation_result(validation: dict) -> ValidationResult:
    """Convert Python validation dict to camelCase ValidationResult."""
    return ValidationResult(
        status=validation.get("status", "fail"),
        missingHard=validation.get("missing_hard", []),
        missingSoft=validation.get("missing_soft", []),
        disqualifyingReasons=validation.get("disqualifying_reasons", []),
        sectorExcluded=validation.get("sector_excluded", False),
        sectorExcludedReason=validation.get("sector_excluded_reason"),
        defaultsApplied=validation.get("defaults_applied", []),
        substituteWarnings=validation.get("substitute_warnings", []),
    )


def build_company_snapshot(summary: dict, validation: dict) -> CompanySnapshot:
    """Build CompanySnapshot from summary and validation dicts."""
    # Build revenue history from fiscal_years data
    revenue_history = []
    fiscal_years = summary.get("fiscal_years", {})
    for fy_str, fy_data in fiscal_years.items():
        try:
            year = int(fy_str)
            revenue = fy_data.get("revenue")
            if revenue is not None:
                revenue_history.append(RevenuePoint(year=year, revenue=float(revenue)))
        except (ValueError, TypeError):
            pass
    revenue_history.sort(key=lambda x: x.year)

    # Calculate market cap from price and shares
    current_price = float(summary.get("current_price", 0) or 0)
    shares = float(summary.get("shares_outstanding", 0) or 0)
    market_cap = current_price * shares if current_price > 0 and shares > 0 else 0

    return CompanySnapshot(
        ticker=summary.get("ticker", ""),
        companyName=summary.get("company_name", ""),
        sicCode=int(summary.get("sic_code", 0) or 0),
        sicDescription=summary.get("sic_description", ""),
        currentPrice=current_price,
        sharesOutstanding=shares,
        marketCap=market_cap,
        revenueHistory=revenue_history,
        validation=build_validation_result(validation),
    )


def compute_debt_equity_split(assumptions: Dict[str, Any]) -> Dict[str, float]:
    """
    Compute debt/equity split from assumptions.

    Formula:
    - Total Uses = Entry EBITDA × Entry Multiple × (1 + Transaction Fee %)
    - New Debt = Entry EBITDA × Leverage Multiple
    - Debt % = New Debt / Total Uses = Leverage Multiple / (Entry Multiple × (1 + Transaction Fee %))
    - Equity % = 1 - Debt %

    Note: Entry EBITDA cancels out, so the split depends only on the multiples and fee.
    """
    entry_multiple = assumptions.get("entryMultiple", 8.0)
    leverage_multiple = assumptions.get("leverageMultiple", 5.5)
    transaction_fee_pct = assumptions.get("transactionFeePct", 0.02)

    total_uses_factor = entry_multiple * (1 + transaction_fee_pct)
    debt_pct = leverage_multiple / total_uses_factor if total_uses_factor > 0 else 0
    equity_pct = 1 - debt_pct

    return {
        "debtPct": round(debt_pct, 4),
        "equityPct": round(equity_pct, 4),
    }


MAX_CAPEX_PCT = 0.15  # Cap CapEx at 15% of revenue for LBO modeling


def build_default_assumptions(summary: dict, validation: dict) -> Dict[str, Any]:
    """Build default assumptions from summary data.

    Returns dict with 'assumptions' and 'adjustments' keys.
    'adjustments' contains info about any values that were capped/modified.
    """
    # Calculate revenue growth rate
    growth_rate, _, _ = calculate_revenue_growth_rate(summary)

    # Get EBITDA margin, capex %, and D&A % from fiscal_years data
    ebitda_margin = 0.30  # Default
    capex_pct = 0.03
    da_pct = 0.03
    raw_capex_pct = None  # Track original value if capped

    fiscal_years = summary.get("fiscal_years", {})

    # Find most recent year with valid data
    for fy_str in sorted(fiscal_years.keys(), reverse=True):
        fy_data = fiscal_years[fy_str]
        revenue = fy_data.get("revenue")
        ebitda = fy_data.get("ebitda_calculated")
        capex = fy_data.get("capex")
        da = fy_data.get("da")

        if revenue is not None and revenue > 0:
            if ebitda is not None:
                ebitda_margin = ebitda / revenue
            if capex is not None:
                raw_capex_pct = abs(capex) / revenue
                capex_pct = raw_capex_pct
            if da is not None:
                da_pct = da / revenue
            break

    # Cap CapEx at MAX_CAPEX_PCT to keep model realistic
    capex_capped = False
    if capex_pct > MAX_CAPEX_PCT:
        capex_capped = True
        capex_pct = MAX_CAPEX_PCT

    return {
        "assumptions": {
            "entryMultiple": 8.0,
            "offerPremium": 0.25,
            "leverageMultiple": 5.5,
            "transactionFeePct": 0.02,
            "revenueGrowth": growth_rate,
            "ebitdaMargin": ebitda_margin,
            "capexPct": capex_pct,
            "daPct": da_pct,
            "nwcPct": 0.0,
            "interestRate": 0.08,
            "mandatoryAmortPct": 0.01,
            "exitYear": 5,
            "exitMultiple": 8.0,
            "taxRate": 0.25,
        },
        "adjustments": {
            "capexCapped": capex_capped,
            "rawCapexPct": raw_capex_pct,
        },
    }


def build_assumption_meta(summary: dict, validation: dict, adjustments: Optional[Dict[str, Any]] = None) -> List[AssumptionMeta]:
    """Build assumption metadata for the frontend."""
    # Check for defaulted/substituted fields
    defaults = validation.get("defaults_applied", [])
    subs = validation.get("substitute_warnings", [])
    adjustments = adjustments or {}

    def get_flag(key: str) -> Optional[str]:
        key_lower = key.lower()
        for d in defaults:
            if key_lower in d.lower():
                return "defaulted"
        for s in subs:
            if key_lower in s.lower():
                return "substituted"
        return None

    # Check if CapEx was capped
    capex_capped = adjustments.get("capexCapped", False)
    raw_capex_pct = adjustments.get("rawCapexPct")
    capex_source = "Most recent fiscal year"
    if capex_capped and raw_capex_pct:
        capex_source = f"Capped at 15% (actual: {raw_capex_pct*100:.1f}%)"

    return [
        AssumptionMeta(key="entryMultiple", label="Entry EV/EBITDA Multiple", group="deal", format="multiple", source="User assumption", flag=None),
        AssumptionMeta(key="offerPremium", label="Offer Premium", group="deal", format="percent", source="User assumption", flag=None),
        AssumptionMeta(key="leverageMultiple", label="Leverage Multiple", group="deal", format="multiple", source="User assumption", flag=None),
        AssumptionMeta(key="transactionFeePct", label="Transaction Fee %", group="deal", format="percent", source="User assumption", flag=None),
        AssumptionMeta(key="revenueGrowth", label="Revenue Growth Rate", group="operating", format="percent", source="Calculated from historicals", flag=get_flag("revenue_growth")),
        AssumptionMeta(key="ebitdaMargin", label="EBITDA Margin", group="operating", format="percent", source="Most recent fiscal year", flag=get_flag("ebitda")),
        AssumptionMeta(key="capexPct", label="CapEx % of Revenue", group="operating", format="percent", source=capex_source, flag="substituted" if capex_capped else get_flag("capex")),
        AssumptionMeta(key="daPct", label="D&A % of Revenue", group="operating", format="percent", source="Most recent fiscal year", flag=get_flag("depreciation")),
        AssumptionMeta(key="nwcPct", label="Change in NWC %", group="operating", format="percent", source="User assumption", flag=None),
        AssumptionMeta(key="interestRate", label="Interest Rate", group="debt", format="percent", source="User assumption", flag=None),
        AssumptionMeta(key="mandatoryAmortPct", label="Mandatory Amortization %", group="debt", format="percent", source="User assumption", flag=None),
        AssumptionMeta(key="exitYear", label="Exit Year", group="exit", format="years", source="User assumption", flag=None),
        AssumptionMeta(key="exitMultiple", label="Exit EV/EBITDA Multiple", group="exit", format="multiple", source="User assumption", flag=None),
        AssumptionMeta(key="taxRate", label="Tax Rate", group="exit", format="percent", source="User assumption", flag=None),
    ]


def convert_assumptions_to_summary_format(assumptions: Dict[str, Any], summary: dict) -> dict:
    """
    Update summary dict with user assumptions in the format expected by excel_generator.
    Maps camelCase frontend keys to snake_case backend keys.
    """
    # Create a copy to avoid mutating original
    updated = dict(summary)

    # Map frontend keys to backend keys
    updated["entry_multiple"] = assumptions.get("entryMultiple", 8.0)
    updated["offer_premium"] = assumptions.get("offerPremium", 0.25)
    updated["leverage_multiple"] = assumptions.get("leverageMultiple", 5.5)
    updated["transaction_fee_pct"] = assumptions.get("transactionFeePct", 0.02)
    updated["revenue_growth_rate"] = assumptions.get("revenueGrowth", 0.05)
    updated["ebitda_margin_pct"] = assumptions.get("ebitdaMargin", 0.30)
    updated["capex_pct"] = assumptions.get("capexPct", 0.03)
    updated["da_pct"] = assumptions.get("daPct", 0.03)
    updated["nwc_pct"] = assumptions.get("nwcPct", 0.0)
    updated["interest_rate"] = assumptions.get("interestRate", 0.08)
    updated["mandatory_amort_pct"] = assumptions.get("mandatoryAmortPct", 0.01)
    updated["exit_year"] = assumptions.get("exitYear", 5)
    updated["exit_multiple"] = assumptions.get("exitMultiple", 8.0)
    updated["tax_rate"] = assumptions.get("taxRate", 0.25)

    return updated


def build_sensitivity_grid(data, base_entry: float, base_exit: float, exit_year: int) -> List[SensitivityCell]:
    """Build the 5x5 sensitivity grid from extracted data."""
    cells = []

    # Get sensitivity values from extracted data
    moic_min = data.moic_min.value if data.moic_min else 0
    moic_max = data.moic_max.value if data.moic_max else 0
    moic_base = data.moic_base.value if data.moic_base else 0
    irr_min = data.irr_min.value if data.irr_min else 0
    irr_max = data.irr_max.value if data.irr_max else 0
    irr_base = data.irr_base.value if data.irr_base else 0

    # Build 5x5 grid
    entry_steps = [-2, -1, 0, 1, 2]
    exit_steps = [-2, -1, 0, 1, 2]

    for exit_offset in exit_steps:
        for entry_offset in entry_steps:
            entry = base_entry + entry_offset * 0.5
            exit = base_exit + exit_offset * 0.5
            is_base = (entry_offset == 0 and exit_offset == 0)

            # Interpolate MOIC and IRR based on position in grid
            # This is a simplified approximation - the real values are in the Excel file
            if is_base:
                moic = moic_base
                irr = irr_base
            else:
                # Linear interpolation from base
                moic = moic_base - (entry - base_entry) * 0.18 + (exit - base_exit) * 0.22
                irr = pow(moic, 1/exit_year) - 1 if moic > 0 else 0

            cells.append(SensitivityCell(
                entryMultiple=round(entry, 1),
                exitMultiple=round(exit, 1),
                moic=round(moic, 2),
                irr=round(irr, 4),
                isBase=is_base,
            ))

    return cells


# =============================================================================
# FASTAPI APP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if not SEC_CONTACT_EMAIL:
        print("WARNING: SEC_CONTACT_EMAIL not set - /analyze will fail")
    if not TWELVE_DATA_API_KEY:
        print("WARNING: TWELVE_DATA_API_KEY not set - price data will be unavailable")
    yield
    # Shutdown
    pass


app = FastAPI(
    title="AIO LBO API",
    description="Backend API for AIO LBO analysis tool",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
# In production, set FRONTEND_URL to restrict to your actual frontend domain
cors_origins = (
    [origin.strip() for origin in FRONTEND_URL.split(",") if origin.strip()]
    if FRONTEND_URL
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "secEmailConfigured": bool(SEC_CONTACT_EMAIL),
        "twelveDataConfigured": bool(TWELVE_DATA_API_KEY),
    }


@app.post("/analyze")
async def analyze_ticker(request: Request, body: AnalyzeRequest):
    """
    Analyze a ticker - fetch data from SEC EDGAR and Twelve Data, run validation.
    """
    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please wait before making another request."
        )

    # Check configuration
    if not SEC_CONTACT_EMAIL:
        raise HTTPException(
            status_code=500,
            detail="Server not configured: SEC_CONTACT_EMAIL missing"
        )

    ticker = body.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker is required")

    try:
        # Fetch data
        summary = fetch_ticker_data(
            ticker=ticker,
            sec_user_agent=SEC_USER_AGENT,
            twelve_data_key=TWELVE_DATA_API_KEY or "",
            verbose=False,
            skip_price=not bool(TWELVE_DATA_API_KEY),
        )

        if summary is None:
            return {
                "ok": False,
                "ticker": ticker,
                "validation": {
                    "status": "fail",
                    "missingHard": ["Unable to fetch data from SEC EDGAR"],
                    "missingSoft": [],
                    "disqualifyingReasons": ["Ticker not found or SEC EDGAR unavailable"],
                    "sectorExcluded": False,
                    "sectorExcludedReason": None,
                    "defaultsApplied": [],
                    "substituteWarnings": [],
                },
                "nextSteps": [
                    "Verify the ticker symbol is correct",
                    "Check if the company files 10-K reports with the SEC",
                    "Try again in a few moments if SEC EDGAR is temporarily unavailable",
                ],
            }

        # Validate
        validation = validate(summary)

        if validation["status"] == "fail":
            return {
                "ok": False,
                "ticker": ticker,
                "validation": build_validation_result(validation).model_dump(),
                "nextSteps": [
                    "Review the disqualifying conditions above",
                    "This company may not be suitable for LBO analysis",
                ] + validation.get("disqualifying_reasons", [])[:2],
            }

        # Success - build response
        snapshot = build_company_snapshot(summary, validation)
        assumptions_result = build_default_assumptions(summary, validation)
        assumptions = assumptions_result["assumptions"]
        adjustments = assumptions_result["adjustments"]
        meta = build_assumption_meta(summary, validation, adjustments)

        # Compute debt/equity split from default assumptions
        debt_equity_split = compute_debt_equity_split(assumptions)

        # Store summary in request state for generate endpoint
        # (In production, you'd use a cache like Redis)

        return {
            "ok": True,
            "snapshot": snapshot.model_dump(),
            "assumptions": assumptions,
            "assumptionMeta": [m.model_dump() for m in meta],
            # Computed debt/equity split for immediate display
            "debtPct": debt_equity_split["debtPct"],
            "equityPct": debt_equity_split["equityPct"],
            # Include summary for generate endpoint (internal use)
            "_summary": summary,
            "_validation": validation,
        }

    except Exception as e:
        print(f"Error analyzing {ticker}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate")
async def generate_model(body: GenerateRequest):
    """
    Generate the Excel model, extract results, and optionally generate narrative.
    """
    ticker = body.ticker.strip().upper()
    assumptions = body.assumptions
    user_overrides = body.userOverrides
    llm_provider = body.llmProvider
    llm_api_key = body.llmApiKey

    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker is required")

    try:
        # Re-fetch data (or use cached - in production use Redis)
        summary = fetch_ticker_data(
            ticker=ticker,
            sec_user_agent=SEC_USER_AGENT,
            twelve_data_key=TWELVE_DATA_API_KEY or "",
            verbose=False,
            skip_price=not bool(TWELVE_DATA_API_KEY),
        )

        if summary is None:
            raise HTTPException(status_code=400, detail=f"Unable to fetch data for {ticker}")

        # Apply user-provided overrides BEFORE validation
        # This allows user to fill in missing data that would otherwise fail/degrade
        user_provided_fields = []
        if user_overrides:
            if user_overrides.currentPrice is not None:
                summary["current_price"] = user_overrides.currentPrice
                summary["current_price_source"] = "user_provided"
                user_provided_fields.append("current_price")
            if user_overrides.totalDebt is not None:
                # Apply to most recent fiscal year
                fiscal_years = summary.get("fiscal_years", {})
                for fy_str in sorted(fiscal_years.keys(), reverse=True):
                    fiscal_years[fy_str]["total_debt"] = user_overrides.totalDebt
                    break
                user_provided_fields.append("total_debt")
            if user_overrides.cash is not None:
                fiscal_years = summary.get("fiscal_years", {})
                for fy_str in sorted(fiscal_years.keys(), reverse=True):
                    fiscal_years[fy_str]["cash"] = user_overrides.cash
                    break
                user_provided_fields.append("cash")
            if user_overrides.capex is not None:
                fiscal_years = summary.get("fiscal_years", {})
                for fy_str in sorted(fiscal_years.keys(), reverse=True):
                    fiscal_years[fy_str]["capex"] = user_overrides.capex
                    break
                user_provided_fields.append("capex")

        # Store user_provided_fields in summary for downstream use
        summary["user_provided_fields"] = user_provided_fields

        validation = validate(summary)

        # Update summary with user assumptions
        updated_summary = convert_assumptions_to_summary_format(assumptions, summary)

        # Create temp directory for workbook
        temp_dir = tempfile.mkdtemp()
        try:
            # Generate workbook
            workbook_path = generate_workbook(
                validated_summary={"summary": updated_summary, "validation": validation},
                output_dir=temp_dir,
            )

            # Recalculate workbook (LibreOffice or Excel COM)
            recalc_path = recalculate_workbook(workbook_path)

            # Extract data
            data = extract_data_from_workbook(recalc_path)

            # Compute feasibility score
            score = compute_feasibility_score(data)

            # Read workbook bytes for base64 encoding
            with open(workbook_path, "rb") as f:
                xlsx_bytes = f.read()
            xlsx_base64 = base64.b64encode(xlsx_bytes).decode("utf-8")

            # Build score breakdown
            feasibility = ScoreBreakdown(
                total=score.total_score,
                irr=score.irr_score,
                moic=score.moic_score,
                debtService=score.debt_service_score,
                leverageReduction=score.leverage_reduction_score,
                dataQuality=score.data_quality_score,
                max=ScoreBreakdownMax(),
            )

            # Extract key values
            irr = data.irr.value if data.irr else 0
            moic = data.moic.value if data.moic else 0
            exit_equity = data.exit_equity.value if data.exit_equity else 0

            # Build sensitivity grid
            base_entry = assumptions.get("entryMultiple", 8.0)
            base_exit = assumptions.get("exitMultiple", 8.0)
            exit_year = assumptions.get("exitYear", 5)
            sensitivity = build_sensitivity_grid(data, base_entry, base_exit, exit_year)

            # Generate narrative if LLM credentials provided
            report_markdown = ""
            if llm_provider and llm_api_key:
                try:
                    report_markdown = generate_narrative(
                        structured_data=data,
                        score_breakdown=score,
                        provider=llm_provider,
                        api_key=llm_api_key,
                    )
                except LLMProviderError as e:
                    report_markdown = f"*Error generating narrative: {e}*"

            # Compute debt/equity split from user's assumptions
            debt_equity_split = compute_debt_equity_split(assumptions)

            return {
                "irr": irr,
                "moic": moic,
                "feasibility": feasibility.model_dump(),
                "exitEquityValue": exit_equity,
                "reportMarkdown": report_markdown,
                "xlsxBase64": xlsx_base64,
                "sensitivity": [s.model_dump() for s in sensitivity],
                "debtPct": debt_equity_split["debtPct"],
                "equityPct": debt_equity_split["equityPct"],
            }

        finally:
            # Cleanup temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating model for {ticker}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/compare")
async def compare_models(
    file_a: UploadFile = File(...),
    file_b: UploadFile = File(...),
    llmProvider: Optional[str] = Form(None),
    llmApiKey: Optional[str] = Form(None),
):
    """
    Compare two Excel models and generate commentary.
    """
    temp_dir = tempfile.mkdtemp()
    try:
        # Save uploaded files
        path_a = Path(temp_dir) / "file_a.xlsx"
        path_b = Path(temp_dir) / "file_b.xlsx"

        with open(path_a, "wb") as f:
            content = await file_a.read()
            f.write(content)

        with open(path_b, "wb") as f:
            content = await file_b.read()
            f.write(content)

        # Run comparison
        result = compare_files(str(path_a), str(path_b))

        # Build deltas for response
        deltas = []
        od = result.output_diff
        sd = od.score_diff

        # Format helpers
        def pct(v): return f"{v * 100:.1f}%"
        def x(v): return f"{v:.2f}x"
        def curr(v):
            if abs(v) >= 1e9:
                return f"${v/1e9:.2f}B"
            elif abs(v) >= 1e6:
                return f"${v/1e6:.2f}M"
            return f"${v:,.0f}"

        if result.mode == "scenario":
            # Add input diffs first
            for diff in result.input_diffs:
                val_a = diff.value_a
                val_b = diff.value_b
                if diff.format_type == "pct":
                    val_a_str = f"{val_a * 100:.1f}%" if val_a else "N/A"
                    val_b_str = f"{val_b * 100:.1f}%" if val_b else "N/A"
                elif diff.format_type == "multiple":
                    val_a_str = f"{val_a:.2f}x" if val_a else "N/A"
                    val_b_str = f"{val_b:.2f}x" if val_b else "N/A"
                else:
                    val_a_str = str(val_a)
                    val_b_str = str(val_b)

                deltas.append(ComparisonDelta(
                    metric=diff.display_name,
                    valueA=val_a_str,
                    valueB=val_b_str,
                    change=f"{diff.abs_diff:+.2f}" if diff.format_type == "multiple" else
                           f"{diff.abs_diff * 100:+.1f}%" if diff.format_type == "pct" else
                           f"{diff.abs_diff:+.0f}",
                ))

        # Add output metrics
        deltas.extend([
            ComparisonDelta(metric="IRR", valueA=pct(od.irr_a), valueB=pct(od.irr_b),
                          change=f"{od.irr_diff:+.1f} pp"),
            ComparisonDelta(metric="MOIC", valueA=x(od.moic_a), valueB=x(od.moic_b),
                          change=f"{od.moic_diff:+.2f}x"),
            ComparisonDelta(metric="Feasibility", valueA=f"{sd.total_a:.0f}", valueB=f"{sd.total_b:.0f}",
                          change=f"{sd.total_diff:+.1f}"),
            ComparisonDelta(metric="Exit Equity", valueA=curr(od.exit_equity_a), valueB=curr(od.exit_equity_b),
                          change=curr(od.exit_equity_diff)),
        ])

        # Generate commentary if LLM credentials provided
        commentary = None
        if llmProvider and llmApiKey:
            try:
                commentary = generate_comparison_commentary(result, llmProvider, llmApiKey)
            except LLMProviderError as e:
                commentary = f"Error generating commentary: {e}"

        return ComparisonResultResponse(
            mode=result.mode,
            deltas=[d.model_dump() for d in deltas],
            commentary=commentary,
        ).model_dump()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
