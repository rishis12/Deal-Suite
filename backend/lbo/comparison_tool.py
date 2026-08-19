"""
AIO LBO Comparison Tool

Compares two generated .xlsx files (base case vs scenario, or two different companies)
and produces a deterministic diff plus minimal AI commentary.

Reuses the extraction and LLM provider infrastructure from report_generator.py.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

# Import from report_generator - reuse existing infrastructure
from .report_generator import (
    ExtractedData,
    ScoreBreakdown,
    TaggedValue,
    recalculate_workbook,
    extract_data_from_workbook,
    compute_feasibility_score,
    generate_narrative,
    sanitize_for_console,
    format_currency,
    format_pct,
    format_multiple,
    LLM_PROVIDERS,
    LLMProviderError,
)


# =============================================================================
# PART 2: DETERMINISTIC DIFF
# =============================================================================

ComparisonMode = Literal["scenario", "company"]


@dataclass
class FieldDiff:
    """A single field difference between two files."""
    field_name: str
    display_name: str
    value_a: Any
    value_b: Any
    abs_diff: float
    rel_diff: Optional[float] = None  # Percentage difference where applicable
    format_type: str = "number"  # "number", "pct", "multiple", "currency", "int"


@dataclass
class ScoreDiff:
    """Difference in feasibility score components."""
    total_a: float
    total_b: float
    total_diff: float

    irr_score_a: float
    irr_score_b: float
    irr_score_diff: float

    moic_score_a: float
    moic_score_b: float
    moic_score_diff: float

    debt_service_score_a: float
    debt_service_score_b: float
    debt_service_score_diff: float

    leverage_reduction_score_a: float
    leverage_reduction_score_b: float
    leverage_reduction_score_diff: float

    data_quality_score_a: float
    data_quality_score_b: float
    data_quality_score_diff: float


@dataclass
class OutputDiff:
    """Difference in headline output metrics."""
    irr_a: float
    irr_b: float
    irr_diff: float  # In percentage points

    moic_a: float
    moic_b: float
    moic_diff: float

    exit_equity_a: float
    exit_equity_b: float
    exit_equity_diff: float

    leverage_entry_a: float
    leverage_entry_b: float
    leverage_exit_a: float
    leverage_exit_b: float

    score_diff: ScoreDiff


@dataclass
class ComparisonResult:
    """Full comparison result."""
    mode: ComparisonMode

    # Company info
    ticker_a: str
    ticker_b: str
    company_a: str
    company_b: str
    sector_a: str
    sector_b: str

    # For Mode A (scenario): which inputs changed
    input_diffs: List[FieldDiff] = field(default_factory=list)

    # For Mode B (company): all 14 assumptions side by side
    assumptions_comparison: List[Tuple[str, str, Any, Any]] = field(default_factory=list)

    # For both modes: output comparison
    output_diff: OutputDiff = None

    # Raw data for LLM prompt
    data_a: ExtractedData = None
    data_b: ExtractedData = None
    score_a: ScoreBreakdown = None
    score_b: ScoreBreakdown = None


# The 14 independent assumptions with their display names and format types
ASSUMPTIONS_FIELDS = [
    ("entry_multiple", "Entry EV/EBITDA Multiple", "multiple"),
    ("revenue_growth_rate", "Revenue Growth Rate", "pct"),
    ("ebitda_margin", "EBITDA Margin %", "pct"),
    ("offer_premium", "Offer Premium %", "pct"),
    ("leverage_multiple", "Leverage Multiple", "multiple"),
    ("interest_rate", "Interest Rate", "pct"),
    ("tax_rate", "Tax Rate", "pct"),
    ("capex_pct", "Capex %", "pct"),
    ("da_pct", "D&A %", "pct"),
    ("nwc_pct", "Change in NWC %", "pct"),
    ("exit_year", "Exit Year", "int"),
    ("exit_multiple", "Exit EV/EBITDA Multiple", "multiple"),
    ("transaction_fee_pct", "Transaction Fee %", "pct"),
    ("amortization_pct", "Mandatory Amortization %", "pct"),
]


def get_tagged_value(data: ExtractedData, field_name: str) -> Any:
    """Extract the raw value from a TaggedValue field."""
    val = getattr(data, field_name, None)
    if isinstance(val, TaggedValue):
        return val.value
    return val


def compare_files(
    filepath_a: str,
    filepath_b: str,
) -> ComparisonResult:
    """
    Compare two .xlsx files and produce a deterministic diff.

    Reuses the same recalculation + extraction logic from report_generator.
    """
    # Extract data from both files using existing infrastructure
    print(f"Processing file A: {filepath_a}")
    recalc_a = recalculate_workbook(filepath_a)
    data_a = extract_data_from_workbook(recalc_a)
    score_a = compute_feasibility_score(data_a)

    print(f"Processing file B: {filepath_b}")
    recalc_b = recalculate_workbook(filepath_b)
    data_b = extract_data_from_workbook(recalc_b)
    score_b = compute_feasibility_score(data_b)

    # Determine mode based on ticker comparison
    ticker_a = get_tagged_value(data_a, "ticker") or ""
    ticker_b = get_tagged_value(data_b, "ticker") or ""

    if ticker_a.upper() == ticker_b.upper():
        mode = "scenario"
        print(f"Mode A detected: Scenario comparison (same ticker: {ticker_a})")
    else:
        mode = "company"
        print(f"Mode B detected: Company comparison ({ticker_a} vs {ticker_b})")

    # Build result
    result = ComparisonResult(
        mode=mode,
        ticker_a=ticker_a,
        ticker_b=ticker_b,
        company_a=get_tagged_value(data_a, "company_name") or "",
        company_b=get_tagged_value(data_b, "company_name") or "",
        sector_a=get_tagged_value(data_a, "sector") or "",
        sector_b=get_tagged_value(data_b, "sector") or "",
        data_a=data_a,
        data_b=data_b,
        score_a=score_a,
        score_b=score_b,
    )

    # Compare the 14 assumptions
    for field_name, display_name, format_type in ASSUMPTIONS_FIELDS:
        val_a = get_tagged_value(data_a, field_name)
        val_b = get_tagged_value(data_b, field_name)

        # Convert to float for comparison (handle None)
        float_a = float(val_a) if val_a is not None else 0.0
        float_b = float(val_b) if val_b is not None else 0.0

        # For Mode A: only record fields that actually differ
        # For Mode B: record all fields for side-by-side comparison
        if mode == "company":
            result.assumptions_comparison.append((field_name, display_name, val_a, val_b))
        else:
            # Check if values differ (with small tolerance for floating point)
            if abs(float_a - float_b) > 1e-9:
                abs_diff = float_b - float_a
                rel_diff = None
                if float_a != 0:
                    rel_diff = (float_b - float_a) / abs(float_a)

                result.input_diffs.append(FieldDiff(
                    field_name=field_name,
                    display_name=display_name,
                    value_a=val_a,
                    value_b=val_b,
                    abs_diff=abs_diff,
                    rel_diff=rel_diff,
                    format_type=format_type,
                ))

    # Compute output diff (same for both modes)
    irr_a = get_tagged_value(data_a, "irr") or 0
    irr_b = get_tagged_value(data_b, "irr") or 0
    moic_a = get_tagged_value(data_a, "moic") or 0
    moic_b = get_tagged_value(data_b, "moic") or 0
    exit_equity_a = get_tagged_value(data_a, "exit_equity") or 0
    exit_equity_b = get_tagged_value(data_b, "exit_equity") or 0
    leverage_entry_a = get_tagged_value(data_a, "leverage_ratio_year1") or 0
    leverage_entry_b = get_tagged_value(data_b, "leverage_ratio_year1") or 0
    leverage_exit_a = get_tagged_value(data_a, "leverage_ratio_exit") or 0
    leverage_exit_b = get_tagged_value(data_b, "leverage_ratio_exit") or 0

    score_diff = ScoreDiff(
        total_a=score_a.total_score,
        total_b=score_b.total_score,
        total_diff=score_b.total_score - score_a.total_score,
        irr_score_a=score_a.irr_score,
        irr_score_b=score_b.irr_score,
        irr_score_diff=score_b.irr_score - score_a.irr_score,
        moic_score_a=score_a.moic_score,
        moic_score_b=score_b.moic_score,
        moic_score_diff=score_b.moic_score - score_a.moic_score,
        debt_service_score_a=score_a.debt_service_score,
        debt_service_score_b=score_b.debt_service_score,
        debt_service_score_diff=score_b.debt_service_score - score_a.debt_service_score,
        leverage_reduction_score_a=score_a.leverage_reduction_score,
        leverage_reduction_score_b=score_b.leverage_reduction_score,
        leverage_reduction_score_diff=score_b.leverage_reduction_score - score_a.leverage_reduction_score,
        data_quality_score_a=score_a.data_quality_score,
        data_quality_score_b=score_b.data_quality_score,
        data_quality_score_diff=score_b.data_quality_score - score_a.data_quality_score,
    )

    result.output_diff = OutputDiff(
        irr_a=irr_a,
        irr_b=irr_b,
        irr_diff=(irr_b - irr_a) * 100,  # Convert to percentage points
        moic_a=moic_a,
        moic_b=moic_b,
        moic_diff=moic_b - moic_a,
        exit_equity_a=exit_equity_a,
        exit_equity_b=exit_equity_b,
        exit_equity_diff=exit_equity_b - exit_equity_a,
        leverage_entry_a=leverage_entry_a,
        leverage_entry_b=leverage_entry_b,
        leverage_exit_a=leverage_exit_a,
        leverage_exit_b=leverage_exit_b,
        score_diff=score_diff,
    )

    return result


# =============================================================================
# PART 3: LLM COMMENTARY
# =============================================================================

def format_field_value(value: Any, format_type: str) -> str:
    """Format a field value for display."""
    if value is None:
        return "N/A"
    if format_type == "pct":
        return f"{value * 100:.1f}%"
    elif format_type == "multiple":
        return f"{value:.2f}x"
    elif format_type == "currency":
        return format_currency(value)
    elif format_type == "int":
        return str(int(value))
    else:
        return f"{value:.2f}"


def build_scenario_comparison_prompt(result: ComparisonResult) -> str:
    """Build the LLM prompt for Mode A (scenario comparison)."""

    # Build input changes section
    input_changes = []
    for diff in result.input_diffs:
        val_a_str = format_field_value(diff.value_a, diff.format_type)
        val_b_str = format_field_value(diff.value_b, diff.format_type)

        if diff.rel_diff is not None:
            rel_str = f" ({diff.rel_diff * 100:+.1f}% change)"
        else:
            rel_str = ""

        input_changes.append(f"- {diff.display_name}: {val_a_str} -> {val_b_str}{rel_str}")

    input_changes_str = "\n".join(input_changes) if input_changes else "No assumption changes detected."

    # Build output changes section
    od = result.output_diff
    sd = od.score_diff

    # Format direction words
    irr_dir = "increased" if od.irr_diff > 0 else "decreased"
    moic_dir = "increased" if od.moic_diff > 0 else "decreased"
    score_dir = "increased" if sd.total_diff > 0 else "decreased"

    prompt = f"""You are analyzing the comparison between two LBO scenarios for the same company.

=== COMPANY ===
Ticker: {result.ticker_a}
Company: {result.company_a}

=== INPUT CHANGES (Base Case -> Scenario) ===
{input_changes_str}

=== OUTPUT CHANGES ===
IRR: {od.irr_a * 100:.1f}% -> {od.irr_b * 100:.1f}% ({od.irr_diff:+.1f} percentage points)
MOIC: {od.moic_a:.2f}x -> {od.moic_b:.2f}x ({od.moic_diff:+.2f}x)
Exit Equity Value: {format_currency(od.exit_equity_a)} -> {format_currency(od.exit_equity_b)} ({format_currency(od.exit_equity_diff)} change)

Leverage Ratio (Year 1): {od.leverage_entry_a:.2f}x -> {od.leverage_entry_b:.2f}x
Leverage Ratio (Exit): {od.leverage_exit_a:.2f}x -> {od.leverage_exit_b:.2f}x

Feasibility Score: {sd.total_a:.1f}/100 -> {sd.total_b:.1f}/100 ({sd.total_diff:+.1f} points)
  - IRR Score: {sd.irr_score_a:.1f}/30 -> {sd.irr_score_b:.1f}/30 ({sd.irr_score_diff:+.1f})
  - MOIC Score: {sd.moic_score_a:.1f}/20 -> {sd.moic_score_b:.1f}/20 ({sd.moic_score_diff:+.1f})
  - Debt Service Score: {sd.debt_service_score_a:.1f}/25 -> {sd.debt_service_score_b:.1f}/25 ({sd.debt_service_score_diff:+.1f})
  - Leverage Reduction Score: {sd.leverage_reduction_score_a:.1f}/15 -> {sd.leverage_reduction_score_b:.1f}/15 ({sd.leverage_reduction_score_diff:+.1f})
  - Data Quality Score: {sd.data_quality_score_a:.1f}/10 -> {sd.data_quality_score_b:.1f}/10 ({sd.data_quality_score_diff:+.1f})

=== INSTRUCTIONS ===
Write a brief comparison summary with these sections:

1. **Input Changes**: State which assumptions changed between the base case and scenario (pull directly from the INPUT CHANGES section above).

2. **Resulting Impact**: State the resulting changes in headline metrics (IRR, MOIC, Feasibility Score) using the exact numbers from OUTPUT CHANGES above.

3. **Summary**: One or two sentences noting the directional impact of the changes.

CRITICAL CONSTRAINTS:
- Describe WHAT changed, not WHY beyond what's directly computable from the diff.
- Example of acceptable commentary: "IRR decreased 6.2 percentage points, driven by the EBITDA margin assumption dropping from 32.7% to 29.0%"
- Example of NOT acceptable: "This suggests the sponsor overestimated cost synergies" (speculation)
- Do NOT speculate about deal strategy, market conditions, negotiation dynamics, or qualitative business factors.
- Keep it concise - a few short paragraphs total.
- Use exact numbers from the diff, do not round or approximate.
"""
    return prompt


def build_company_comparison_prompt(result: ComparisonResult) -> str:
    """Build the LLM prompt for Mode B (company comparison)."""

    # Build assumptions comparison table
    assumptions_lines = []
    for field_name, display_name, val_a, val_b in result.assumptions_comparison:
        # Find the format type
        format_type = "number"
        for fn, dn, ft in ASSUMPTIONS_FIELDS:
            if fn == field_name:
                format_type = ft
                break

        val_a_str = format_field_value(val_a, format_type)
        val_b_str = format_field_value(val_b, format_type)

        # Check if values are the same or different
        same = abs(float(val_a or 0) - float(val_b or 0)) < 1e-9
        marker = "" if same else " *"

        assumptions_lines.append(f"  {display_name}: {val_a_str} vs {val_b_str}{marker}")

    assumptions_str = "\n".join(assumptions_lines)

    # Company profiles
    data_a = result.data_a
    data_b = result.data_b

    entry_revenue_a = get_tagged_value(data_a, "entry_revenue") or 0
    entry_revenue_b = get_tagged_value(data_b, "entry_revenue") or 0
    entry_ebitda_a = get_tagged_value(data_a, "entry_ebitda") or 0
    entry_ebitda_b = get_tagged_value(data_b, "entry_ebitda") or 0

    # Output comparison
    od = result.output_diff
    sd = od.score_diff

    # Determine which company is stronger on each metric
    irr_stronger = result.ticker_a if od.irr_a > od.irr_b else result.ticker_b
    moic_stronger = result.ticker_a if od.moic_a > od.moic_b else result.ticker_b
    score_stronger = result.ticker_a if sd.total_a > sd.total_b else result.ticker_b

    prompt = f"""You are analyzing a comparison between two different companies' LBO deals.

=== COMPANY A: {result.ticker_a} ===
Company: {result.company_a}
Sector: {result.sector_a}
Entry Revenue: {format_currency(entry_revenue_a)}
Entry EBITDA: {format_currency(entry_ebitda_a)}

=== COMPANY B: {result.ticker_b} ===
Company: {result.company_b}
Sector: {result.sector_b}
Entry Revenue: {format_currency(entry_revenue_b)}
Entry EBITDA: {format_currency(entry_ebitda_b)}

=== DEAL ASSUMPTIONS COMPARISON ===
(* indicates differing values between deals)
{assumptions_str}

=== OUTPUT COMPARISON ===
                         {result.ticker_a:>12}    {result.ticker_b:>12}
IRR:                     {od.irr_a * 100:>11.1f}%   {od.irr_b * 100:>11.1f}%
MOIC:                    {od.moic_a:>11.2f}x   {od.moic_b:>11.2f}x
Exit Equity Value:       {format_currency(od.exit_equity_a):>12}   {format_currency(od.exit_equity_b):>12}
Leverage (Year 1):       {od.leverage_entry_a:>11.2f}x   {od.leverage_entry_b:>11.2f}x
Leverage (Exit):         {od.leverage_exit_a:>11.2f}x   {od.leverage_exit_b:>11.2f}x

Feasibility Score:       {sd.total_a:>11.1f}    {sd.total_b:>11.1f}
  - IRR Score:           {sd.irr_score_a:>11.1f}    {sd.irr_score_b:>11.1f}  (out of 30)
  - MOIC Score:          {sd.moic_score_a:>11.1f}    {sd.moic_score_b:>11.1f}  (out of 20)
  - Debt Service:        {sd.debt_service_score_a:>11.1f}    {sd.debt_service_score_b:>11.1f}  (out of 25)
  - Leverage Reduction:  {sd.leverage_reduction_score_a:>11.1f}    {sd.leverage_reduction_score_b:>11.1f}  (out of 15)
  - Data Quality:        {sd.data_quality_score_a:>11.1f}    {sd.data_quality_score_b:>11.1f}  (out of 10)

=== INSTRUCTIONS ===
Write a brief comparison summary with these sections:

1. **Company Profiles**: Briefly describe the two companies and note whether their deal assumptions were set the same or differently (refer to the * markers in the assumptions table).

2. **Metric Comparison**: State how their headline metrics compare ({irr_stronger} shows stronger IRR, {moic_stronger} shows stronger MOIC, {score_stronger} shows higher Feasibility Score) using the exact numbers from the OUTPUT COMPARISON above.

3. **Summary**: One or two sentences noting which deal looks financially stronger based ONLY on the computed metrics.

CRITICAL CONSTRAINTS:
- Use "Company A vs Company B" framing, NOT "increased/decreased from base case" language (there is no natural base case here).
- Do NOT speculate about WHY one company's underlying business performs differently.
- No commentary on business strategy, competitive positioning, market conditions, or qualitative factors.
- Stick to "{result.ticker_a} shows X, {result.ticker_b} shows Y" comparisons grounded in the numbers.
- Keep it concise - a few short paragraphs total.
- Use exact numbers from the comparison, do not round or approximate.
"""
    return prompt


def generate_comparison_commentary(
    result: ComparisonResult,
    provider: str,
    api_key: str,
) -> str:
    """Generate LLM commentary for the comparison."""

    if result.mode == "scenario":
        prompt = build_scenario_comparison_prompt(result)
    else:
        prompt = build_company_comparison_prompt(result)

    # Reuse existing provider infrastructure
    return generate_narrative(result.data_a, result.score_a, provider, api_key, prompt_override=prompt)


# =============================================================================
# PRINTING / OUTPUT
# =============================================================================

def print_comparison_result(result: ComparisonResult):
    """Print the deterministic comparison result (without LLM commentary)."""

    print("\n" + "=" * 70)
    if result.mode == "scenario":
        print(f"SCENARIO COMPARISON: {result.ticker_a}")
        print(f"Base Case vs Modified Scenario")
    else:
        print(f"COMPANY COMPARISON: {result.ticker_a} vs {result.ticker_b}")
    print("=" * 70)

    if result.mode == "scenario":
        # Print input changes
        print("\n--- INPUT CHANGES ---")
        if result.input_diffs:
            for diff in result.input_diffs:
                val_a_str = format_field_value(diff.value_a, diff.format_type)
                val_b_str = format_field_value(diff.value_b, diff.format_type)
                print(f"  {diff.display_name}: {val_a_str} -> {val_b_str}")
        else:
            print("  No assumption changes detected.")
    else:
        # Print company profiles
        print(f"\n--- COMPANY A: {result.ticker_a} ---")
        print(f"  Company: {result.company_a}")
        print(f"  Sector: {result.sector_a}")

        print(f"\n--- COMPANY B: {result.ticker_b} ---")
        print(f"  Company: {result.company_b}")
        print(f"  Sector: {result.sector_b}")

        # Print assumptions comparison
        print("\n--- DEAL ASSUMPTIONS ---")
        print(f"  {'Field':<30} {result.ticker_a:>15} {result.ticker_b:>15}")
        print("  " + "-" * 60)
        for field_name, display_name, val_a, val_b in result.assumptions_comparison:
            format_type = "number"
            for fn, dn, ft in ASSUMPTIONS_FIELDS:
                if fn == field_name:
                    format_type = ft
                    break
            val_a_str = format_field_value(val_a, format_type)
            val_b_str = format_field_value(val_b, format_type)
            print(f"  {display_name:<30} {val_a_str:>15} {val_b_str:>15}")

    # Print output comparison (same for both modes)
    od = result.output_diff
    sd = od.score_diff

    print("\n--- OUTPUT METRICS ---")
    if result.mode == "scenario":
        print(f"  IRR: {od.irr_a * 100:.1f}% -> {od.irr_b * 100:.1f}% ({od.irr_diff:+.1f} pp)")
        print(f"  MOIC: {od.moic_a:.2f}x -> {od.moic_b:.2f}x ({od.moic_diff:+.2f}x)")
        print(f"  Exit Equity: {format_currency(od.exit_equity_a)} -> {format_currency(od.exit_equity_b)}")
        print(f"  Leverage (Y1): {od.leverage_entry_a:.2f}x -> {od.leverage_entry_b:.2f}x")
        print(f"  Leverage (Exit): {od.leverage_exit_a:.2f}x -> {od.leverage_exit_b:.2f}x")
    else:
        print(f"  {'Metric':<25} {result.ticker_a:>15} {result.ticker_b:>15}")
        print("  " + "-" * 55)
        print(f"  {'IRR':<25} {od.irr_a * 100:>14.1f}% {od.irr_b * 100:>14.1f}%")
        print(f"  {'MOIC':<25} {od.moic_a:>14.2f}x {od.moic_b:>14.2f}x")
        print(f"  {'Exit Equity':<25} {format_currency(od.exit_equity_a):>15} {format_currency(od.exit_equity_b):>15}")
        print(f"  {'Leverage (Y1)':<25} {od.leverage_entry_a:>14.2f}x {od.leverage_entry_b:>14.2f}x")
        print(f"  {'Leverage (Exit)':<25} {od.leverage_exit_a:>14.2f}x {od.leverage_exit_b:>14.2f}x")

    print("\n--- FEASIBILITY SCORE ---")
    if result.mode == "scenario":
        print(f"  Total: {sd.total_a:.1f}/100 -> {sd.total_b:.1f}/100 ({sd.total_diff:+.1f})")
        print(f"    IRR Score: {sd.irr_score_a:.1f}/30 -> {sd.irr_score_b:.1f}/30 ({sd.irr_score_diff:+.1f})")
        print(f"    MOIC Score: {sd.moic_score_a:.1f}/20 -> {sd.moic_score_b:.1f}/20 ({sd.moic_score_diff:+.1f})")
        print(f"    Debt Service: {sd.debt_service_score_a:.1f}/25 -> {sd.debt_service_score_b:.1f}/25 ({sd.debt_service_score_diff:+.1f})")
        print(f"    Leverage Reduction: {sd.leverage_reduction_score_a:.1f}/15 -> {sd.leverage_reduction_score_b:.1f}/15 ({sd.leverage_reduction_score_diff:+.1f})")
        print(f"    Data Quality: {sd.data_quality_score_a:.1f}/10 -> {sd.data_quality_score_b:.1f}/10 ({sd.data_quality_score_diff:+.1f})")
    else:
        print(f"  {'Component':<25} {result.ticker_a:>15} {result.ticker_b:>15}")
        print("  " + "-" * 55)
        print(f"  {'Total':<25} {sd.total_a:>14.1f} {sd.total_b:>14.1f}  /100")
        print(f"  {'  IRR Score':<25} {sd.irr_score_a:>14.1f} {sd.irr_score_b:>14.1f}  /30")
        print(f"  {'  MOIC Score':<25} {sd.moic_score_a:>14.1f} {sd.moic_score_b:>14.1f}  /20")
        print(f"  {'  Debt Service':<25} {sd.debt_service_score_a:>14.1f} {sd.debt_service_score_b:>14.1f}  /25")
        print(f"  {'  Leverage Reduction':<25} {sd.leverage_reduction_score_a:>14.1f} {sd.leverage_reduction_score_b:>14.1f}  /15")
        print(f"  {'  Data Quality':<25} {sd.data_quality_score_a:>14.1f} {sd.data_quality_score_b:>14.1f}  /10")


# =============================================================================
# MAIN / CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Compare two LBO model spreadsheets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare base case vs scenario (same ticker - Mode A)
  python comparison_tool.py base_case.xlsx scenario.xlsx --provider gemini

  # Compare two different companies (Mode B)
  python comparison_tool.py AAPL.xlsx CCL.xlsx --provider gemini

  # Diff only (no LLM commentary)
  python comparison_tool.py file_a.xlsx file_b.xlsx --diff-only
"""
    )

    parser.add_argument("file_a", help="First .xlsx file (base case or Company A)")
    parser.add_argument("file_b", help="Second .xlsx file (scenario or Company B)")
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai", "gemini"],
        default="gemini",
        help="LLM provider for commentary (default: gemini)"
    )
    parser.add_argument(
        "--api-key",
        help="API key for LLM provider (or use environment variable)"
    )
    parser.add_argument(
        "--diff-only",
        action="store_true",
        help="Only show deterministic diff, skip LLM commentary"
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Show the LLM prompt instead of calling the API"
    )

    args = parser.parse_args()

    # Validate files exist
    if not os.path.exists(args.file_a):
        print(f"ERROR: File not found: {args.file_a}")
        sys.exit(1)
    if not os.path.exists(args.file_b):
        print(f"ERROR: File not found: {args.file_b}")
        sys.exit(1)

    # Get API key
    api_key = args.api_key
    if not api_key and not args.diff_only:
        env_var = f"{args.provider.upper()}_API_KEY"
        api_key = os.environ.get(env_var)

    try:
        # Compare files
        result = compare_files(args.file_a, args.file_b)

        # Print deterministic diff
        print_comparison_result(result)

        # Show prompt or generate commentary
        if args.show_prompt:
            if result.mode == "scenario":
                prompt = build_scenario_comparison_prompt(result)
            else:
                prompt = build_company_comparison_prompt(result)
            print("\n" + "=" * 70)
            print("LLM PROMPT")
            print("=" * 70)
            print(prompt)
        elif not args.diff_only:
            if not api_key:
                print(f"\n(Skipping LLM commentary - no API key provided)")
                print(f"Set {args.provider.upper()}_API_KEY or use --api-key")
            else:
                print("\n" + "=" * 70)
                print("GENERATING COMMENTARY...")
                print("=" * 70)

                try:
                    commentary = generate_comparison_commentary(result, args.provider, api_key)
                    print("\n" + "=" * 70)
                    print("COMPARISON COMMENTARY")
                    print("=" * 70)
                    print(sanitize_for_console(commentary))
                except LLMProviderError as e:
                    print(f"\nERROR generating commentary: {e}")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
