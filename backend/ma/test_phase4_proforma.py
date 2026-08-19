"""
Phase 4 test: Pro Forma IS + Accretion/Dilution tabs.

Real workbooks, real recalculation (data_only=True readback), and the four
required scenario checks:
1. Clearly ACCRETIVE deal (high-P/E acquirer, low-P/E target, all-stock)
   — direction reasoned first, model must agree
2. Clearly DILUTIVE deal (all cash+debt, big premium, expensive debt,
   no synergies) — model must show dilution
3. COVID-distorted company (CCL) must NOT produce an absurd revenue
   projection (growth sanity band carried over from AIO LBO)
4. Combined Diluted Shares constant across every projection year

Prices are synthetic inputs chosen to construct the P/E relationships the
directional scenarios require (disclosed inline).
"""

import re
from pathlib import Path

from openpyxl import load_workbook

from . import data_layer as dl
from .validator import validate_pair
from .excel_generator import generate_ma_workbook
from .recalc import recalculate_workbook

OUT_DIR = Path(__file__).parent / "test_output"

failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(f"{name}: {detail}")


def read_ref(wb, ref: str):
    m = re.match(r"'(.+)'!\$([A-Z]+)\$(\d+)", ref)
    return wb[m.group(1)][f"{m.group(2)}{int(m.group(3))}"].value


def build_and_recalc(pair, deal_assumptions, out_name):
    verdict = validate_pair(pair)
    assert verdict["status"] != "fail", verdict["disqualifying_reasons"]
    out_path = str(OUT_DIR / out_name)
    refs = generate_ma_workbook(pair, verdict, out_path,
                                deal_assumptions=deal_assumptions)
    recalc_path = recalculate_workbook(out_path)
    wb = load_workbook(recalc_path, data_only=True)
    return refs, wb


def fetch_pair_with_prices(acq_t, tgt_t, acq_price, tgt_price):
    pair = dl.fetch_ma_pair(acq_t, tgt_t, verbose=False, skip_price=True)
    pair["acquirer"]["current_price"] = acq_price
    pair["target"]["current_price"] = tgt_price
    for role in ("acquirer", "target"):
        pair[role]["current_price_source"] = "synthetic-test"
    return pair


def main():
    OUT_DIR.mkdir(exist_ok=True)

    # ==================================================================
    # SCENARIO 1: CLEARLY ACCRETIVE
    # MSFT (EPS ~11.8, price set 600 -> P/E ~51) acquires POOL
    # (EPS ~13.4, price set 100 -> P/E ~7.5; with 25% premium ~9.4).
    # All-stock: acquirer issues cheap-looking shares for cheap earnings
    # -> P/E arbitrage says accretive. Zero synergies, so any accretion
    # is structural, not assumed.
    # ==================================================================
    print(f"\n{'='*70}\nSCENARIO 1: EXPECT ACCRETIVE (MSFT buys POOL, all-stock)\n{'='*70}")
    pair = fetch_pair_with_prices("MSFT", "POOL", 600.0, 100.0)
    refs, wb = build_and_recalc(
        pair,
        {"pct_cash": 0.0, "pct_debt": 0.0},   # all-stock
        "mna_p4_accretive_MSFT_POOL.xlsx")

    ad_y1 = read_ref(wb, refs["ad_year1"])
    ad_final = read_ref(wb, refs["ad_final"])
    print(f"  Year 1 A/D: {ad_y1*100:+.2f}%, Final year A/D: {ad_final*100:+.2f}%")
    check("accretive scenario shows Year-1 accretion", ad_y1 is not None and ad_y1 > 0,
          f"ad_y1={ad_y1!r}")
    check("headline cells match trajectory",
          read_ref(wb, refs["headline_year1"]) == ad_y1
          and read_ref(wb, refs["headline_final"]) == ad_final)

    # Hand-verify Year 1 Pro Forma EPS from recalculated inputs
    acq_rev = read_ref(wb, refs["acq_revenue"])
    tgt_rev = read_ref(wb, refs["tgt_revenue"])
    acq_g = read_ref(wb, refs["acq_growth"])
    tgt_g = read_ref(wb, refs["tgt_growth"])
    acq_margin = read_ref(wb, refs["acq_op_margin"])
    tgt_margin = read_ref(wb, refs["tgt_op_margin"])
    inc_da = read_ref(wb, refs["incremental_da"])
    tax = read_ref(wb, refs["tax_rate"])
    acq_sh = read_ref(wb, refs["acq_diluted_shares"])
    new_sh = read_ref(wb, refs["new_shares_issued"])

    ebit1 = acq_rev * (1 + acq_g) * acq_margin + tgt_rev * (1 + tgt_g) * tgt_margin
    pretax1 = ebit1 - inc_da  # no debt, no cash used in this structure
    ni1 = pretax1 - max(0, pretax1 * tax)
    exp_eps1 = ni1 / (acq_sh + new_sh)
    sheet_eps1 = read_ref(wb, refs["proforma_eps_cells"][0])
    check("hand-verified Year-1 Pro Forma EPS",
          abs(sheet_eps1 - exp_eps1) <= max(1e-9 * abs(exp_eps1), 1e-6),
          f"sheet={sheet_eps1!r} vs hand={exp_eps1!r}")

    standalone = read_ref(wb, refs["standalone_eps"])
    check("hand-verified Year-1 accretion %",
          abs((sheet_eps1 / standalone - 1) - ad_y1) < 1e-9,
          f"derived={(sheet_eps1/standalone-1)!r} vs sheet={ad_y1!r}")

    # Check 4: Combined shares constant across all years
    share_vals = [read_ref(wb, ref) for ref in refs["comb_shares_cells"]]
    check("combined diluted shares constant across years",
          len(set(share_vals)) == 1, f"values={share_vals}")

    # ==================================================================
    # SCENARIO 2: CLEARLY DILUTIVE
    # POOL (EPS ~13.4, price set 80 -> P/E ~6) pays a 50% premium for
    # WING (EPS ~2.35, price set 400 -> P/E ~170), all cash+debt at 10%
    # debt / 5% foregone cash, zero synergies. Financing cost dwarfs the
    # tiny earnings acquired -> must be dilutive.
    # ==================================================================
    print(f"\n{'='*70}\nSCENARIO 2: EXPECT DILUTIVE (POOL buys WING, cash+debt)\n{'='*70}")
    pair = fetch_pair_with_prices("POOL", "WING", 80.0, 400.0)
    refs2, wb2 = build_and_recalc(
        pair,
        {"pct_cash": 0.50, "pct_debt": 0.50, "offer_premium": 0.50,
         "new_debt_rate": 0.10, "foregone_cash_rate": 0.05},
        "mna_p4_dilutive_POOL_WING.xlsx")

    ad_y1 = read_ref(wb2, refs2["ad_year1"])
    ad_final = read_ref(wb2, refs2["ad_final"])
    print(f"  Year 1 A/D: {ad_y1*100:+.2f}%, Final year A/D: {ad_final*100:+.2f}%")
    check("dilutive scenario shows Year-1 dilution", ad_y1 is not None and ad_y1 < 0,
          f"ad_y1={ad_y1!r}")

    new_shares = read_ref(wb2, refs2["new_shares_issued"])
    check("all cash+debt deal issues ~0 new shares",
          abs(new_shares) < 1e-6, f"new_shares={new_shares!r}")

    share_vals2 = [read_ref(wb2, ref) for ref in refs2["comb_shares_cells"]]
    check("combined shares constant (scenario 2)",
          len(set(share_vals2)) == 1, f"values={share_vals2}")

    # ==================================================================
    # SCENARIO 3: COVID-DISTORTED GROWTH SANITY (CCL as acquirer)
    # CCL's post-COVID rebound YoY rates are absurd (77-540%). The median
    # + sanity band must clamp the default to 3% with a visible flag, and
    # the projection must stay sane.
    # ==================================================================
    print(f"\n{'='*70}\nSCENARIO 3: COVID-DISTORTED GROWTH (CCL buys FIZZ)\n{'='*70}")
    pair = fetch_pair_with_prices("CCL", "FIZZ", 25.0, 45.0)

    # First confirm the raw median really is implausible for CCL, so this
    # scenario genuinely exercises the band
    import statistics
    fys = sorted(pair["acquirer"]["fiscal_years"])
    revs = [pair["acquirer"]["fiscal_years"][y]["revenue"] for y in fys]
    raw_rates = [(revs[i] - revs[i-1]) / revs[i-1]
                 for i in range(1, len(revs)) if revs[i-1] and revs[i]]
    raw_median = statistics.median(raw_rates)
    print(f"  CCL raw YoY rates: {[f'{r*100:.0f}%' for r in raw_rates]}, "
          f"median {raw_median*100:.1f}%")
    check("CCL raw median is genuinely implausible (band must trigger)",
          raw_median > 0.25 or raw_median < -0.15, f"median={raw_median}")

    refs3, wb3 = build_and_recalc(pair, None, "mna_p4_covid_CCL_FIZZ.xlsx")

    acq_growth = read_ref(wb3, refs3["acq_growth"])
    check("CCL growth default clamped to 3% fallback",
          abs(acq_growth - 0.03) < 1e-12, f"growth={acq_growth!r}")

    # Fallback must carry the visible orange flag (check the ORIGINAL file)
    orig = load_workbook(str(OUT_DIR / "mna_p4_covid_CCL_FIZZ.xlsx"))
    m = re.match(r"'(.+)'!\$([A-Z]+)\$(\d+)", refs3["acq_growth"])
    cell = orig[m.group(1)][f"{m.group(2)}{m.group(3)}"]
    check("fallback growth cell visibly flagged (orange fill + comment)",
          cell.fill.start_color.rgb in ("00FFB366", "FFB366", "FFFFB366")
          and cell.comment is not None,
          f"fill={cell.fill.start_color.rgb}, comment={bool(cell.comment)}")

    # Projection sanity: 5-year combined revenue growth must be modest
    base_rev = read_ref(wb3, refs3["acq_revenue"]) + read_ref(wb3, refs3["tgt_revenue"])
    rows = refs3["proforma_rows"]
    final_col = chr(66 + 5)
    final_rev = wb3["Pro Forma IS"][f"{final_col}{rows['comb_rev_row']}"].value
    ratio = final_rev / base_rev
    check("no absurd combined revenue projection (Y5 < 1.6x base)",
          1.0 < ratio < 1.6, f"Y5/base={ratio:.3f}")

    share_vals3 = [read_ref(wb3, ref) for ref in refs3["comb_shares_cells"]]
    check("combined shares constant (scenario 3)",
          len(set(share_vals3)) == 1, f"values={share_vals3}")

    # Balance check still holds on all three workbooks
    for name, w_, r_ in [("accretive", wb, refs), ("dilutive", wb2, refs2),
                         ("covid", wb3, refs3)]:
        check(f"balance check == 0 ({name})",
              read_ref(w_, r_["balance_check"]) == 0)

    print(f"\n{'='*70}")
    if failures:
        print(f"PHASE 4 TEST RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print(f"  - {f}")
    else:
        print("PHASE 4 TEST RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
