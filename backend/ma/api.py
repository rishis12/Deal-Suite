"""
M&A Modeling Tool - FastAPI Backend

Wraps the Phase 1-7 modules behind a REST contract. This contract is the
SOURCE OF TRUTH the Phase 9 frontend must match (defined here explicitly,
per the AIO LBO lesson where frontend and backend each guessed their own
contract and had to be reconciled later).

Endpoints:
  GET  /health
  POST /analyze  {acquirerTicker, targetTicker}
  POST /generate {acquirerTicker, targetTicker, assumptions?,
                  marketShareTable?, userOverrides?, llmProvider?, llmApiKey?}
  POST /compare  multipart: fileA, fileB (+ optional llmProvider, llmApiKey)

Non-negotiables carried from AIO LBO's hard-won lessons:
- SEC User-Agent constructed HERE as "AppName email" (AIO LBO's API layer
  once reintroduced the bare-email bug even though the fetch module was
  correct) — the exact string is printed at startup and on /analyze.
- LLM SDKs pinned in requirements.txt despite lazy imports.
- CORS origin from FRONTEND_URL env; wildcard only as local-dev default.
- BYOK llmApiKey is used only within the request that carries it: never
  logged, never written to disk, never stored on any object that outlives
  the request. (Audit: the only reads of llmApiKey below pass it directly
  to generate_narrative()/generate_comparison_commentary().)
- Rate limiting on /analyze sized for the DOUBLED per-request cost of a
  two-company fetch (5/min/IP vs AIO LBO's 10/min single-company).
"""

import base64
import io
import json
import os
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import data_layer
from .validator import validate_pair
from .excel_generator import (
    DEFAULT_DEAL_ASSUMPTIONS,
    calculate_revenue_growth_rate,
    generate_ma_workbook,
    load_refs_from_workbook,
)
from .recalc import recalculate_workbook
from .report_generator import (
    LLMProviderError,
    build_report_prompt,
    extract_data_from_workbook,
    generate_narrative,
)
from . import comparison_tool as ct
from openpyxl import load_workbook


# =============================================================================
# CONFIGURATION
# =============================================================================

SEC_CONTACT_EMAIL = os.environ.get("SEC_CONTACT_EMAIL", "")
# SEC requires User-Agent format: "AppName contact@email.com" — constructed
# explicitly here, never the bare email (AIO LBO shipped that exact bug in
# its API layer).
SEC_USER_AGENT = f"MNA-Modeling-Tool {SEC_CONTACT_EMAIL}"

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "")

print("[STARTUP] === CONFIGURATION ===")
print(f"[STARTUP] SEC_CONTACT_EMAIL: '{SEC_CONTACT_EMAIL}'")
print(f"[STARTUP] SEC_USER_AGENT: '{SEC_USER_AGENT}'")
print(f"[STARTUP] TWELVE_DATA_API_KEY: "
      f"{'set (' + TWELVE_DATA_API_KEY[:4] + '...)' if TWELVE_DATA_API_KEY else 'NOT SET (prices will be missing)'}")
print(f"[STARTUP] FRONTEND_URL: '{FRONTEND_URL or '* (local dev default)'}'")

# Rate limiting for /analyze: protects SEC EDGAR and the shared server-side
# Twelve Data quota (~800/day, NOT BYOK). Each /analyze costs ~4-5 SEC calls
# and up to 2 Twelve Data calls (two companies) — double AIO LBO's
# single-company cost, so the per-IP limit is halved from its 10/min.
RATE_LIMIT_WINDOW = 60          # seconds
RATE_LIMIT_MAX_REQUESTS = 5     # per IP per window

# Pipeline note on timeouts: a /generate run (two-company fetch + workbook +
# LibreOffice recalculation + optional LLM call) legitimately takes 20-40+s.
# Uvicorn imposes no per-request timeout by default; keep-alive is raised so
# a reverse proxy or client with a 30s default doesn't kill a valid request.
KEEP_ALIVE_TIMEOUT = 180


@dataclass
class RateLimitEntry:
    timestamps: list


rate_limit_store: Dict[str, RateLimitEntry] = defaultdict(
    lambda: RateLimitEntry(timestamps=[]))


def check_rate_limit(client_ip: str) -> bool:
    """Sliding-window per-IP rate limit. Returns True if allowed."""
    now = time.time()
    entry = rate_limit_store[client_ip]
    entry.timestamps = [t for t in entry.timestamps
                        if now - t < RATE_LIMIT_WINDOW]
    if len(entry.timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    entry.timestamps.append(now)
    return True


# =============================================================================
# REQUEST / RESPONSE MODELS (the Phase 9 contract — camelCase)
# =============================================================================

class AnalyzeRequest(BaseModel):
    acquirerTicker: str
    targetTicker: str


class PriceOverride(BaseModel):
    currentPrice: Optional[float] = None


class UserOverrides(BaseModel):
    acquirer: Optional[PriceOverride] = None
    target: Optional[PriceOverride] = None


class MarketShareRow(BaseModel):
    companyName: str
    marketShare: float  # fraction, e.g. 0.25 for 25%


class GenerateRequest(BaseModel):
    acquirerTicker: str
    targetTicker: str
    assumptions: Optional[Dict[str, Any]] = None
    marketShareTable: Optional[List[MarketShareRow]] = None
    userOverrides: Optional[UserOverrides] = None
    llmProvider: Optional[str] = None
    llmApiKey: Optional[str] = None   # BYOK: request-scoped only, never persisted


class CompanyVerdict(BaseModel):
    ticker: str
    status: str
    missingHard: List[str]
    missingSoft: List[str]
    disqualifyingReasons: List[str]
    sectorExcluded: bool
    sectorExcludedReason: Optional[str]
    defaultsApplied: List[str]
    substituteWarnings: List[str]
    warnings: List[str]
    goodwillPrecisionDegraded: bool


class PairValidation(BaseModel):
    status: str
    disqualifyingReasons: List[str]
    acquirer: CompanyVerdict
    target: CompanyVerdict


class CompanySnapshot(BaseModel):
    ticker: str
    companyName: str
    sicCode: str
    sicDescription: str
    fiscalYear: Optional[int]
    currentPrice: Optional[float]
    dilutedShares: Optional[float]
    dilutedEps: Optional[float]
    revenue: Optional[float]
    operatingIncome: Optional[float]
    da: Optional[float]
    ebitda: Optional[float]
    netIncome: Optional[float]
    totalDebt: Optional[float]
    cash: Optional[float]
    totalAssets: Optional[float]
    totalLiabilities: Optional[float]
    growthDefault: float
    growthIsFallback: bool
    growthNote: str


class AnalyzeResponse(BaseModel):
    validation: PairValidation
    acquirer: CompanySnapshot
    target: CompanySnapshot
    defaultAssumptions: Dict[str, Any]


class HHIResult(BaseModel):
    assessed: bool
    preMergerHHI: Optional[float] = None
    postMergerHHI: Optional[float] = None
    deltaHHI: Optional[float] = None
    preMergerClass: Optional[str] = None
    postMergerClass: Optional[str] = None
    presumptiveConcern: Optional[str] = None


class GenerateResponse(BaseModel):
    validation: PairValidation
    sourcesUses: Dict[str, Optional[float]]
    ppa: Dict[str, Optional[float]]
    standaloneEps: Optional[float]
    proFormaEpsByYear: List[Optional[float]]
    accretionDilutionByYear: List[Optional[float]]
    crossover: Optional[str]
    hhi: HHIResult
    report: Optional[str]
    reportError: Optional[str]
    xlsxBase64: str
    filename: str


class ComparisonResponse(BaseModel):
    mode: str
    dealLabelA: str
    dealLabelB: str
    inputDiffs: List[Dict[str, Any]]
    assumptionsComparison: List[Dict[str, Any]]
    adByYearA: List[Optional[float]]
    adByYearB: List[Optional[float]]
    epsByYearA: List[Optional[float]]
    epsByYearB: List[Optional[float]]
    goodwillA: Optional[float]
    goodwillB: Optional[float]
    hhiA: Optional[Dict[str, Any]]
    hhiB: Optional[Dict[str, Any]]
    commentary: Optional[str]
    commentaryError: Optional[str]


# =============================================================================
# APP
# =============================================================================

app = FastAPI(
    title="M&A Modeling Tool API",
    description="Two-company M&A accretion/dilution model backend",
    version="1.0.0",
)

# CORS: FRONTEND_URL locks production down; wildcard is local-dev only
allowed_origins = ([o.strip() for o in FRONTEND_URL.split(",") if o.strip()]
                   if FRONTEND_URL else ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "secUserAgent": SEC_USER_AGENT}


# =============================================================================
# HELPERS
# =============================================================================

def _require_email():
    if not SEC_CONTACT_EMAIL:
        raise HTTPException(
            status_code=503,
            detail="Server misconfigured: SEC_CONTACT_EMAIL is not set")


def _fetch_pair_or_422(acq: str, tgt: str, skip_price: bool = False) -> dict:
    _require_email()
    # Log the exact header actually used for this request — verifying the
    # constructed string, not assuming it (the AIO LBO API-layer bug).
    print(f"[SEC] User-Agent for this request: '{SEC_USER_AGENT}'")
    try:
        pair = data_layer.fetch_ma_pair(
            acq, tgt,
            sec_user_agent=SEC_USER_AGENT,
            twelve_data_key=TWELVE_DATA_API_KEY,
            verbose=False,
            skip_price=skip_price or not TWELVE_DATA_API_KEY,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return pair


def _verdict_model(v: dict) -> CompanyVerdict:
    return CompanyVerdict(
        ticker=v["ticker"],
        status=v["status"],
        missingHard=v["missing_hard"],
        missingSoft=v["missing_soft"],
        disqualifyingReasons=v["disqualifying_reasons"],
        sectorExcluded=v["sector_excluded"],
        sectorExcludedReason=v["sector_excluded_reason"],
        defaultsApplied=v["defaults_applied"],
        substituteWarnings=v["substitute_warnings"],
        warnings=v["warnings"],
        goodwillPrecisionDegraded=v["goodwill_precision_degraded"],
    )


def _pair_validation_model(verdict: dict) -> PairValidation:
    return PairValidation(
        status=verdict["status"],
        disqualifyingReasons=verdict["disqualifying_reasons"],
        acquirer=_verdict_model(verdict["acquirer"]),
        target=_verdict_model(verdict["target"]),
    )


def _snapshot(profile: dict) -> CompanySnapshot:
    fys = profile.get("fiscal_years", {})
    fy = max(fys) if fys else None
    d = fys.get(fy, {}) if fy else {}
    growth, is_fallback, note = calculate_revenue_growth_rate(profile)
    op_inc, da = d.get("operating_income"), d.get("da")
    return CompanySnapshot(
        ticker=profile.get("ticker", ""),
        companyName=profile.get("company_name", ""),
        sicCode=str(profile.get("sic_code", "")),
        sicDescription=profile.get("sic_description", ""),
        fiscalYear=fy,
        currentPrice=profile.get("current_price"),
        dilutedShares=d.get("diluted_shares") or profile.get("diluted_shares"),
        dilutedEps=d.get("diluted_eps"),
        revenue=d.get("revenue"),
        operatingIncome=op_inc,
        da=da,
        ebitda=(op_inc + da) if op_inc is not None and da is not None else None,
        netIncome=d.get("net_income"),
        totalDebt=d.get("total_debt"),
        cash=d.get("cash"),
        totalAssets=d.get("total_assets"),
        totalLiabilities=d.get("total_liabilities"),
        growthDefault=growth,
        growthIsFallback=is_fallback,
        growthNote=note,
    )


def _apply_overrides(pair: dict, overrides: Optional[UserOverrides]):
    if not overrides:
        return
    for role in ("acquirer", "target"):
        ov = getattr(overrides, role, None)
        if ov and ov.currentPrice is not None and pair.get(role):
            pair[role]["current_price"] = ov.currentPrice
            pair[role]["current_price_source"] = "user_provided"
            pair[role].setdefault("user_provided_fields", []).append("current_price")


def _hhi_model(data) -> HHIResult:
    if not data.hhi_assessed:
        return HHIResult(assessed=False)
    return HHIResult(
        assessed=True,
        preMergerHHI=data.pre_merger_hhi,
        postMergerHHI=data.post_merger_hhi,
        deltaHHI=data.delta_hhi,
        preMergerClass=data.pre_merger_class,
        postMergerClass=data.post_merger_class,
        presumptiveConcern=data.presumptive_concern,
    )


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: Request, body: AnalyzeRequest):
    """Fetch + validate both companies; return snapshots and pre-filled
    assumptions."""
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({RATE_LIMIT_MAX_REQUESTS} analyses "
                   f"per {RATE_LIMIT_WINDOW}s). The two-company fetch is "
                   f"expensive on shared quotas — please wait a moment.")

    pair = _fetch_pair_or_422(body.acquirerTicker, body.targetTicker)
    verdict = validate_pair(pair)

    if pair["acquirer"] is None or pair["target"] is None:
        raise HTTPException(
            status_code=422,
            detail={"validation": _pair_validation_model(verdict).model_dump()})

    defaults = dict(DEFAULT_DEAL_ASSUMPTIONS)
    return AnalyzeResponse(
        validation=_pair_validation_model(verdict),
        acquirer=_snapshot(pair["acquirer"]),
        target=_snapshot(pair["target"]),
        defaultAssumptions=defaults,
    )


@app.post("/generate", response_model=GenerateResponse)
def generate(body: GenerateRequest):
    """Build the workbook, recalculate for real, extract results, optionally
    generate the BYOK narrative, and return JSON + base64 xlsx in one
    response (no server-side file storage)."""
    pair = _fetch_pair_or_422(body.acquirerTicker, body.targetTicker)
    _apply_overrides(pair, body.userOverrides)
    verdict = validate_pair(pair)

    if verdict["status"] == "fail":
        raise HTTPException(
            status_code=422,
            detail={"validation": _pair_validation_model(verdict).model_dump()})

    deal_assumptions = None
    if body.assumptions:
        unknown = set(body.assumptions) - set(DEFAULT_DEAL_ASSUMPTIONS)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown assumption keys: {sorted(unknown)}. "
                       f"Valid keys: {sorted(DEFAULT_DEAL_ASSUMPTIONS)}")
        deal_assumptions = body.assumptions

    tmp_dir = tempfile.mkdtemp(prefix="mna_generate_")
    xlsx_path = os.path.join(
        tmp_dir, f"MNA_{pair['acquirer']['ticker']}_{pair['target']['ticker']}.xlsx")

    refs = generate_ma_workbook(pair, verdict, xlsx_path,
                                deal_assumptions=deal_assumptions)

    # Inject the user's market share table (user_provided provenance)
    if body.marketShareTable:
        wb = load_workbook(xlsx_path)
        ws = wb["Market Concentration"]
        table = refs["market_share_table"]
        rows = body.marketShareTable[:len(table["share_cells"])]
        for row_data, name_addr, share_addr in zip(
                rows, table["name_cells"], table["share_cells"]):
            ws[name_addr] = row_data.companyName
            ws[share_addr] = row_data.marketShare
        wb.save(xlsx_path)

    recalc_path = recalculate_workbook(xlsx_path)
    data = extract_data_from_workbook(recalc_path, xlsx_path, refs)

    # Optional BYOK narrative. llmApiKey is passed straight through and
    # goes out of scope with this request — never logged or stored.
    report_text, report_error = None, None
    if body.llmProvider and body.llmApiKey:
        try:
            report_text = generate_narrative(data, body.llmProvider, body.llmApiKey)
        except (LLMProviderError, ValueError) as e:
            report_error = str(e)
    elif body.llmProvider and not body.llmApiKey:
        report_error = "llmProvider given without llmApiKey — report skipped"

    with open(xlsx_path, "rb") as f:
        xlsx_b64 = base64.b64encode(f.read()).decode("ascii")

    return GenerateResponse(
        validation=_pair_validation_model(verdict),
        sourcesUses={
            "purchaseEquityValue": data.get("purchase_equity_value"),
            "transactionFees": data.get("transaction_fees"),
            "totalUses": data.get("total_uses"),
            "cashUsed": data.get("cash_used"),
            "newDebt": data.get("new_debt"),
            "newStockIssued": data.get("new_stock_issued"),
            "newSharesIssued": data.get("new_shares_issued"),
            "balanceCheck": data.get("balance_check"),
        },
        ppa={
            "targetBookEquity": data.get("tgt_book_equity"),
            "premiumOverBook": data.get("premium_over_book"),
            "assetStepUp": data.get("asset_step_up"),
            "goodwill": data.get("goodwill"),
            "incrementalDA": data.get("incremental_da"),
        },
        standaloneEps=data.get("standalone_eps"),
        proFormaEpsByYear=data.proforma_eps_by_year,
        accretionDilutionByYear=data.ad_by_year,
        crossover=data.crossover,
        hhi=_hhi_model(data),
        report=report_text,
        reportError=report_error,
        xlsxBase64=xlsx_b64,
        filename=os.path.basename(xlsx_path),
    )


@app.post("/compare", response_model=ComparisonResponse)
def compare(
    fileA: UploadFile = File(...),
    fileB: UploadFile = File(...),
    llmProvider: Optional[str] = Form(None),
    llmApiKey: Optional[str] = Form(None),   # BYOK: request-scoped only
):
    """Compare two previously generated workbooks (Phase 7 tool)."""
    tmp_dir = tempfile.mkdtemp(prefix="mna_compare_")
    path_a = os.path.join(tmp_dir, "fileA.xlsx")
    path_b = os.path.join(tmp_dir, "fileB.xlsx")
    with open(path_a, "wb") as f:
        f.write(fileA.file.read())
    with open(path_b, "wb") as f:
        f.write(fileB.file.read())

    try:
        result = ct.compare_files(path_a, path_b)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    commentary, commentary_error = None, None
    if llmProvider and llmApiKey:
        try:
            commentary = ct.generate_comparison_commentary(
                result, llmProvider, llmApiKey)
        except (LLMProviderError, ValueError) as e:
            commentary_error = str(e)

    return ComparisonResponse(
        mode=result.mode,
        dealLabelA=result.deal_label_a,
        dealLabelB=result.deal_label_b,
        inputDiffs=[{
            "field": d.field_name,
            "displayName": d.display_name,
            "valueA": d.value_a,
            "valueB": d.value_b,
            "formatType": d.format_type,
        } for d in result.input_diffs],
        assumptionsComparison=[{
            "field": fn, "displayName": dn, "valueA": va, "valueB": vb,
        } for fn, dn, va, vb in result.assumptions_comparison],
        adByYearA=result.ad_by_year_a,
        adByYearB=result.ad_by_year_b,
        epsByYearA=result.eps_by_year_a,
        epsByYearB=result.eps_by_year_b,
        goodwillA=result.goodwill_a,
        goodwillB=result.goodwill_b,
        hhiA=result.hhi_a,
        hhiB=result.hhi_b,
        commentary=commentary,
        commentaryError=commentary_error,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000,
                timeout_keep_alive=KEEP_ALIVE_TIMEOUT)
