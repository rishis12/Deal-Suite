"""
M&A Comparison Tool

Compares two generated M&A workbook files and produces a deterministic
diff plus minimal LLM commentary. Adapted from AIO LBO's comparison_tool.py
(/reference/backend/) — same deterministic-compute-then-minimal-narration
discipline, extended to ticker PAIRS:

Mode A (scenario): both files share the same Acquirer AND Target ticker —
    same deal, different assumptions. Input diff shows ONLY changed
    assumptions; outputs shown as deltas.

Mode B (deal): either ticker differs — two genuinely different deals.
    Full side-by-side profiles ("Deal A vs Deal B" framing, no deltas —
    there is no natural base case between different deals).

Commentary discipline: lean, factual, states what differs not why —
except the direct-computable-causality exception when a single variable
changed. NO commentary on regulatory approval likelihood, deal execution
probability, or negotiation dynamics in either mode.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from .excel_generator import load_refs_from_workbook
from .recalc import recalculate_workbook
from .report_generator import (
    MAExtractedData,
    extract_data_from_workbook,
    generate_narrative,
    format_currency,
    format_pct,
    LLM_PROVIDERS,
    LLMProviderError,
)


# =============================================================================
# DETERMINISTIC DIFF
# =============================================================================

# The independent deal assumptions from Phase 3 (display name, format)
ASSUMPTION_FIELDS = [
    ("offer_premium", "Offer Premium %", "pct"),
    ("pct_cash", "% Cash", "pct"),
    ("pct_debt", "% Debt", "pct"),
    ("new_debt_rate", "New Debt Interest Rate", "pct"),
    ("foregone_cash_rate", "Foregone Interest Rate on Cash", "pct"),
    ("revenue_synergies_pct", "Revenue Synergies %", "pct"),
    ("cost_synergies_pct", "Cost Synergies %", "pct"),
    ("synergy_ramp_years", "Synergy Ramp Period (years)", "int"),
    ("transaction_fee_pct", "Transaction Fee %", "pct"),
    ("asset_step_up_pct", "Asset Step-Up %", "pct"),
    ("intangible_amort_years", "Intangible Amortization Period (years)", "int"),
    ("tax_rate", "Tax Rate", "pct"),
    ("analysis_years", "Analysis Years", "int"),
]

# Company fundamentals shown side-by-side in Mode B (per company role)
FUNDAMENTAL_FIELDS = [
    ("price", "Share Price", "currency2"),
    ("diluted_shares", "Diluted Shares", "shares"),
    ("diluted_eps", "Diluted EPS", "currency2"),
    ("revenue", "Revenue", "currency"),
    ("op_income", "Operating Income", "currency"),
    ("da", "D&A", "currency"),
    ("net_income", "Net Income", "currency"),
    ("total_debt", "Total Debt", "currency"),
    ("cash", "Cash", "currency"),
    ("total_assets", "Total Assets", "currency"),
    ("total_liabilities", "Total Liabilities", "currency"),
]


@dataclass
class FieldDiff:
    field_name: str
    display_name: str
    value_a: Any
    value_b: Any
    format_type: str = "number"


@dataclass
class MAComparisonResult:
    mode: str  # "scenario" | "deal"

    acq_ticker_a: str
    tgt_ticker_a: str
    acq_ticker_b: str
    tgt_ticker_b: str
    deal_label_a: str
    deal_label_b: str

    # Mode A: only assumptions that differ
    input_diffs: List[FieldDiff] = field(default_factory=list)

    # Mode B: all assumptions side by side
    assumptions_comparison: List[Tuple[str, str, Any, Any]] = field(default_factory=list)

    # Outputs
    ad_by_year_a: List[float] = field(default_factory=list)
    ad_by_year_b: List[float] = field(default_factory=list)
    eps_by_year_a: List[float] = field(default_factory=list)
    eps_by_year_b: List[float] = field(default_factory=list)
    goodwill_a: Optional[float] = None
    goodwill_b: Optional[float] = None

    # HHI (None where not assessed)
    hhi_a: Optional[dict] = None
    hhi_b: Optional[dict] = None
    market_table_differs: bool = False

    data_a: MAExtractedData = None
    data_b: MAExtractedData = None


def format_field_value(value: Any, format_type: str) -> str:
    if value is None:
        return "N/A"
    if format_type == "pct":
        return f"{value * 100:.1f}%"
    if format_type == "int":
        return str(int(value))
    if format_type == "currency":
        return format_currency(value)
    if format_type == "currency2":
        return f"${value:,.2f}"
    if format_type == "shares":
        return f"{value:,.0f}"
    return f"{value:.2f}"


def _extract_file(path: str) -> MAExtractedData:
    refs = load_refs_from_workbook(path)
    recalc_path = recalculate_workbook(path)
    return extract_data_from_workbook(recalc_path, path, refs)


def _hhi_summary(data: MAExtractedData) -> Optional[dict]:
    if not data.hhi_assessed:
        return None
    return {
        "pre": data.pre_merger_hhi,
        "post": data.post_merger_hhi,
        "delta": data.delta_hhi,
        "post_class": data.post_merger_class,
        "presumptive": data.presumptive_concern,
        "shares": (data.values.get("market_shares").value
                   if data.values.get("market_shares") else None),
    }


def compare_files(filepath_a: str, filepath_b: str) -> MAComparisonResult:
    """Compare two generated M&A workbooks deterministically."""
    print(f"Processing file A: {filepath_a}")
    data_a = _extract_file(filepath_a)
    print(f"Processing file B: {filepath_b}")
    data_b = _extract_file(filepath_b)

    def ident(data):
        return ((data.get("acq_ticker") or "").upper(),
                (data.get("tgt_ticker") or "").upper())

    acq_a, tgt_a = ident(data_a)
    acq_b, tgt_b = ident(data_b)

    if acq_a == acq_b and tgt_a == tgt_b:
        mode = "scenario"
        print(f"Mode A detected: scenario comparison (same deal: "
              f"{acq_a} acquiring {tgt_a})")
    else:
        mode = "deal"
        print(f"Mode B detected: deal comparison "
              f"({acq_a}->{tgt_a} vs {acq_b}->{tgt_b})")

    result = MAComparisonResult(
        mode=mode,
        acq_ticker_a=acq_a, tgt_ticker_a=tgt_a,
        acq_ticker_b=acq_b, tgt_ticker_b=tgt_b,
        deal_label_a=f"{acq_a} acquiring {tgt_a}",
        deal_label_b=f"{acq_b} acquiring {tgt_b}",
        data_a=data_a, data_b=data_b,
    )

    # Assumptions: diff (Mode A) or side-by-side (Mode B)
    for field_name, display_name, format_type in ASSUMPTION_FIELDS:
        val_a = data_a.get(field_name)
        val_b = data_b.get(field_name)
        if mode == "deal":
            result.assumptions_comparison.append(
                (field_name, display_name, val_a, val_b))
        else:
            fa = float(val_a) if val_a is not None else 0.0
            fb = float(val_b) if val_b is not None else 0.0
            if abs(fa - fb) > 1e-9:
                result.input_diffs.append(FieldDiff(
                    field_name=field_name, display_name=display_name,
                    value_a=val_a, value_b=val_b, format_type=format_type))

    # Outputs
    result.ad_by_year_a = data_a.ad_by_year
    result.ad_by_year_b = data_b.ad_by_year
    result.eps_by_year_a = data_a.proforma_eps_by_year
    result.eps_by_year_b = data_b.proforma_eps_by_year
    result.goodwill_a = data_a.get("goodwill")
    result.goodwill_b = data_b.get("goodwill")

    result.hhi_a = _hhi_summary(data_a)
    result.hhi_b = _hhi_summary(data_b)
    shares_a = (result.hhi_a or {}).get("shares")
    shares_b = (result.hhi_b or {}).get("shares")
    result.market_table_differs = shares_a != shares_b

    return result


# =============================================================================
# LLM COMMENTARY PROMPTS
# =============================================================================

SCOPE_PROHIBITION = (
    "Do NOT comment on regulatory approval likelihood, review timelines, "
    "required divestitures, deal execution probability, or negotiation "
    "dynamics — even if market concentration figures differ between the "
    "two. You may state computed HHI figures plainly; nothing about "
    "real-world outcome or likelihood."
)


def _ad_series_str(ad: List[float]) -> str:
    return ", ".join(f"Y{i+1} {format_pct(v)}" for i, v in enumerate(ad))


def build_scenario_comparison_prompt(result: MAComparisonResult) -> str:
    """Mode A prompt: same deal, different assumptions."""
    input_changes = [
        f"- {d.display_name}: "
        f"{format_field_value(d.value_a, d.format_type)} -> "
        f"{format_field_value(d.value_b, d.format_type)}"
        for d in result.input_diffs
    ] or ["No assumption changes detected."]

    single_change = len(result.input_diffs) == 1
    # %Cash + %Debt moving together is still "one variable" conceptually
    # (the financing mix), since % stock is the plug
    mix_fields = {"pct_cash", "pct_debt"}
    changed = {d.field_name for d in result.input_diffs}
    mix_only_change = changed and changed.issubset(mix_fields)

    ad_delta = [
        f"Y{i+1}: {format_pct(a)} -> {format_pct(b)} ({(b-a)*100:+.1f} pp)"
        for i, (a, b) in enumerate(zip(result.ad_by_year_a, result.ad_by_year_b))
    ]
    eps_delta = [
        f"Y{i+1}: ${a:,.2f} -> ${b:,.2f}"
        for i, (a, b) in enumerate(zip(result.eps_by_year_a, result.eps_by_year_b))
    ]

    goodwill_line = (
        f"Goodwill: {format_currency(result.goodwill_a)} -> "
        f"{format_currency(result.goodwill_b)}")

    if result.hhi_a and result.hhi_b and result.market_table_differs:
        hhi_line = (f"HHI: post-merger {result.hhi_a['post']:,.0f} -> "
                    f"{result.hhi_b['post']:,.0f}; delta HHI "
                    f"{result.hhi_a['delta']:,.0f} -> {result.hhi_b['delta']:,.0f}")
    elif result.hhi_a and result.hhi_b:
        hhi_line = "HHI: unchanged between scenarios (same market share table)."
    else:
        hhi_line = "HHI: not assessed in one or both scenarios."

    causal_note = ""
    if single_change or mix_only_change:
        causal_note = (
            "\nEXACTLY ONE independent variable changed between these "
            "scenarios (the financing mix counts as one variable — % stock "
            "is always the plug). You MAY therefore state the direct "
            "computable causal relationship (e.g. 'Year 1 accretion "
            "improved because the financing mix shifted toward stock, "
            "reducing new debt and its associated interest expense').")
    else:
        causal_note = (
            "\nMULTIPLE variables changed, so do NOT attribute output "
            "changes to any single input — state what changed, not why.")

    return f"""You are comparing two scenarios of the SAME M&A deal: {result.deal_label_a}.

=== INPUT CHANGES (Scenario A -> Scenario B) ===
{chr(10).join(input_changes)}

=== OUTPUT CHANGES ===
Accretion/(Dilution) by year:
{chr(10).join(ad_delta)}
Pro Forma EPS by year:
{chr(10).join(eps_delta)}
{goodwill_line}
{hhi_line}

=== INSTRUCTIONS ===
Write a brief scenario comparison with these sections:
1. **Input Changes**: state which assumptions changed (from INPUT CHANGES above only).
2. **Resulting Impact**: the accretion/dilution and EPS shifts, using exact numbers.
3. **Summary**: one or two sentences on the directional impact.

CRITICAL CONSTRAINTS:
- Describe WHAT changed; explain WHY only where directly computable.{causal_note}
- {SCOPE_PROHIBITION}
- No speculation about deal strategy, market conditions, or qualitative factors.
- Use exact numbers from the diff. Keep it concise.
"""


def build_deal_comparison_prompt(result: MAComparisonResult) -> str:
    """Mode B prompt: two genuinely different deals, side by side."""
    da, db = result.data_a, result.data_b

    def profile_block(data, label):
        lines = [f"=== {label} ==="]
        lines.append(f"Acquirer: {data.get('acq_name')} ({data.get('acq_ticker')}) "
                     f"— {data.get('acq_sector')}")
        lines.append(f"Target: {data.get('tgt_name')} ({data.get('tgt_ticker')}) "
                     f"— {data.get('tgt_sector')}")
        for role, role_label in (("acq", "Acquirer"), ("tgt", "Target")):
            vals = []
            for key, name, fmt in FUNDAMENTAL_FIELDS:
                vals.append(f"{name} {format_field_value(data.get(f'{role}_{key}'), fmt)}")
            lines.append(f"{role_label} fundamentals: " + "; ".join(vals))
        return "\n".join(lines)

    assumptions_lines = []
    for field_name, display_name, val_a, val_b in result.assumptions_comparison:
        fmt = next((ft for fn, _, ft in ASSUMPTION_FIELDS if fn == field_name),
                   "number")
        assumptions_lines.append(
            f"  {display_name}: {format_field_value(val_a, fmt)} vs "
            f"{format_field_value(val_b, fmt)}")

    def hhi_block(hhi, label):
        if not hhi:
            return f"{label}: market concentration not assessed."
        return (f"{label}: pre {hhi['pre']:,.0f}, post {hhi['post']:,.0f} "
                f"({hhi['post_class']}), delta {hhi['delta']:,.0f}; "
                f"trigger status: {hhi['presumptive']}")

    return f"""You are comparing two DIFFERENT M&A deals side by side.
Deal A: {result.deal_label_a}
Deal B: {result.deal_label_b}

{profile_block(da, 'DEAL A PROFILE')}

{profile_block(db, 'DEAL B PROFILE')}

=== DEAL ASSUMPTIONS (Deal A vs Deal B) ===
{chr(10).join(assumptions_lines)}

=== OUTPUT COMPARISON ===
Deal A Accretion/(Dilution): {_ad_series_str(result.ad_by_year_a)}
Deal B Accretion/(Dilution): {_ad_series_str(result.ad_by_year_b)}
Deal A Goodwill: {format_currency(result.goodwill_a)}
Deal B Goodwill: {format_currency(result.goodwill_b)}
Market concentration —
{hhi_block(result.hhi_a, 'Deal A')}
{hhi_block(result.hhi_b, 'Deal B')}

=== INSTRUCTIONS ===
Write a brief deal comparison with these sections:
1. **Deal Profiles**: describe both deals briefly (companies, premium, financing mix).
2. **Output Comparison**: compare the accretion/dilution trajectories using "Deal A vs Deal B" framing — these are different deals, NOT a base case and a change, so no increase/decrease-from-base language.
3. **Summary**: one or two sentences on which deal looks more accretive based ONLY on the computed figures.

CRITICAL CONSTRAINTS:
- "Deal A vs Deal B" framing throughout.
- {SCOPE_PROHIBITION}
- Do NOT speculate about which deal is more likely to clear antitrust review or close.
- No commentary on strategy, competitive positioning, or qualitative factors.
- Use exact numbers. Keep it concise.
"""


def generate_comparison_commentary(result: MAComparisonResult,
                                   provider: str, api_key: str) -> str:
    """Generate LLM commentary for the comparison (BYOK, key never stored)."""
    if result.mode == "scenario":
        prompt = build_scenario_comparison_prompt(result)
    else:
        prompt = build_deal_comparison_prompt(result)
    return generate_narrative(result.data_a, provider, api_key,
                              prompt_override=prompt)


# =============================================================================
# PRINTING
# =============================================================================

def print_comparison_result(result: MAComparisonResult):
    print("\n" + "=" * 70)
    if result.mode == "scenario":
        print(f"SCENARIO COMPARISON: {result.deal_label_a}")
    else:
        print(f"DEAL COMPARISON: {result.deal_label_a} vs {result.deal_label_b}")
    print("=" * 70)

    if result.mode == "scenario":
        print("\n--- INPUT CHANGES ---")
        if result.input_diffs:
            for d in result.input_diffs:
                print(f"  {d.display_name}: "
                      f"{format_field_value(d.value_a, d.format_type)} -> "
                      f"{format_field_value(d.value_b, d.format_type)}")
        else:
            print("  No assumption changes detected.")

        print("\n--- OUTPUT CHANGES ---")
        print("  Accretion/(Dilution) by year:")
        for i, (a, b) in enumerate(zip(result.ad_by_year_a, result.ad_by_year_b)):
            print(f"    Y{i+1}: {format_pct(a)} -> {format_pct(b)} "
                  f"({(b-a)*100:+.2f} pp)")
        print("  Pro Forma EPS by year:")
        for i, (a, b) in enumerate(zip(result.eps_by_year_a, result.eps_by_year_b)):
            print(f"    Y{i+1}: ${a:,.2f} -> ${b:,.2f}")
        print(f"  Goodwill: {format_currency(result.goodwill_a)} -> "
              f"{format_currency(result.goodwill_b)}")
        if result.market_table_differs and result.hhi_a and result.hhi_b:
            print(f"  Post-merger HHI: {result.hhi_a['post']:,.0f} -> "
                  f"{result.hhi_b['post']:,.0f}")
            print(f"  Delta HHI: {result.hhi_a['delta']:,.0f} -> "
                  f"{result.hhi_b['delta']:,.0f}")
    else:
        for label, data in (("DEAL A", result.data_a), ("DEAL B", result.data_b)):
            print(f"\n--- {label}: {data.get('acq_ticker')} acquiring "
                  f"{data.get('tgt_ticker')} ---")
            print(f"  Acquirer: {data.get('acq_name')} — {data.get('acq_sector')}")
            print(f"  Target: {data.get('tgt_name')} — {data.get('tgt_sector')}")

        print("\n--- DEAL ASSUMPTIONS (Deal A vs Deal B) ---")
        for field_name, display_name, val_a, val_b in result.assumptions_comparison:
            fmt = next((ft for fn, _, ft in ASSUMPTION_FIELDS if fn == field_name),
                       "number")
            print(f"  {display_name:<40} "
                  f"{format_field_value(val_a, fmt):>12} vs "
                  f"{format_field_value(val_b, fmt):>12}")

        print("\n--- ACCRETION/(DILUTION) TRAJECTORIES ---")
        print(f"  Deal A: {_ad_series_str(result.ad_by_year_a)}")
        print(f"  Deal B: {_ad_series_str(result.ad_by_year_b)}")
        print(f"  Deal A Goodwill: {format_currency(result.goodwill_a)}")
        print(f"  Deal B Goodwill: {format_currency(result.goodwill_b)}")


# =============================================================================
# MAIN / CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Compare two M&A model spreadsheets")
    parser.add_argument("file_a", help="First .xlsx (Scenario/Deal A)")
    parser.add_argument("file_b", help="Second .xlsx (Scenario/Deal B)")
    parser.add_argument("--provider", choices=list(LLM_PROVIDERS.keys()),
                        default="gemini")
    parser.add_argument("--api-key", help="BYOK key (or env var)")
    parser.add_argument("--diff-only", action="store_true",
                        help="Deterministic diff only, no LLM commentary")
    parser.add_argument("--show-prompt", action="store_true",
                        help="Print the LLM prompt instead of calling the API")
    args = parser.parse_args()

    for path in (args.file_a, args.file_b):
        if not os.path.exists(path):
            print(f"ERROR: File not found: {path}")
            sys.exit(1)

    api_key = args.api_key
    if not api_key and not args.diff_only:
        api_key = os.environ.get(f"{args.provider.upper()}_API_KEY")

    result = compare_files(args.file_a, args.file_b)
    print_comparison_result(result)

    if args.show_prompt:
        prompt = (build_scenario_comparison_prompt(result)
                  if result.mode == "scenario"
                  else build_deal_comparison_prompt(result))
        print("\n" + "=" * 70 + "\nLLM PROMPT\n" + "=" * 70)
        print(prompt)
    elif not args.diff_only:
        if not api_key:
            print(f"\n(Skipping LLM commentary - no API key provided. "
                  f"Set {args.provider.upper()}_API_KEY or use --api-key)")
        else:
            try:
                commentary = generate_comparison_commentary(
                    result, args.provider, api_key)
                print("\n" + "=" * 70 + "\nCOMPARISON COMMENTARY\n" + "=" * 70)
                print(commentary)
            except LLMProviderError as e:
                print(f"\nERROR generating commentary: {e}")


if __name__ == "__main__":
    main()
