"""
Phase 3 test: generate the workbook for 3 real ticker pairs, force a REAL
recalculation (LibreOffice headless preferred, Excel COM fallback), read
back with openpyxl data_only=True, and verify:

1. Balance Check == exactly 0 for all pairs
2. Goodwill and Incremental D&A hand-verified independently for one pair
3. Every cross-sheet formula resolves to a real non-zero value where
   expected (the named-range bug class from AIO LBO zeroed cells while the
   balance check still passed — so this check is explicit, cell by cell)

Prices are injected synthetically (no Twelve Data key in this environment);
they are model INPUTS, so this exercises all formula paths identically.
"""

import os
import re
from pathlib import Path

from openpyxl import load_workbook

from . import data_layer as dl
from .validator import validate_pair
from .excel_generator import generate_ma_workbook
from .recalc import recalculate_workbook

OUT_DIR = Path(__file__).parent / "test_output"

TEST_PAIRS = [
    ("AAPL", "CROX", 250.0, 90.0),
    ("MSFT", "POOL", 500.0, 320.0),
    ("CCL", "AAL", 25.0, 12.0),   # COVID-distorted / debt-heavy pair
]

failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(f"{name}: {detail}")


def read_ref(wb, ref: str):
    """Read a value from a "'Sheet Name'!$C$12"-style reference."""
    m = re.match(r"'(.+)'!\$([A-Z]+)\$(\d+)", ref)
    sheet, col, row = m.group(1), m.group(2), int(m.group(3))
    return wb[sheet][f"{col}{row}"].value


def main():
    OUT_DIR.mkdir(exist_ok=True)
    ua = dl.get_sec_user_agent()

    for acq_t, tgt_t, acq_price, tgt_price in TEST_PAIRS:
        print(f"\n{'='*70}\nPAIR: {acq_t} (acquirer) + {tgt_t} (target)\n{'='*70}")

        pair = dl.fetch_ma_pair(acq_t, tgt_t, verbose=False, skip_price=True)
        for role, price in (("acquirer", acq_price), ("target", tgt_price)):
            pair[role]["current_price"] = price
            pair[role]["current_price_source"] = "synthetic-test"

        verdict = validate_pair(pair)
        check(f"{acq_t}+{tgt_t} validation not fail", verdict["status"] != "fail",
              str(verdict["disqualifying_reasons"]))
        if verdict["status"] == "fail":
            continue

        out_path = str(OUT_DIR / f"mna_{acq_t}_{tgt_t}.xlsx")
        refs = generate_ma_workbook(pair, verdict, out_path)
        print(f"  Generated: {out_path}")

        # REAL recalculation - never trust formula strings
        recalc_path = recalculate_workbook(out_path)
        wb = load_workbook(recalc_path, data_only=True)
        print(f"  Recalculated via real engine: {recalc_path}")

        # ------------------------------------------------------------------
        # 1. Balance check == exactly 0
        # ------------------------------------------------------------------
        balance = read_ref(wb, refs["balance_check"])
        check(f"{acq_t}+{tgt_t} balance check == 0", balance == 0,
              f"balance={balance!r}")

        # ------------------------------------------------------------------
        # 3. Cross-sheet formulas resolve to real non-zero values
        # (named-range bug class: cells silently $0 while balance passed)
        # ------------------------------------------------------------------
        must_be_nonzero = [
            "acq_market_cap", "tgt_market_cap", "acq_ebitda", "tgt_ebitda",
            "purchase_equity_value", "transaction_fees", "total_uses",
            "cash_used", "new_debt", "new_stock_issued", "new_shares_issued",
            "total_sources", "tgt_book_equity", "premium_over_book",
            "asset_step_up", "goodwill", "incremental_da", "pct_stock",
        ]
        for key in must_be_nonzero:
            val = read_ref(wb, refs[key])
            check(f"{acq_t}+{tgt_t} {key} nonzero",
                  isinstance(val, (int, float)) and val != 0,
                  f"value={val!r}")

        # ------------------------------------------------------------------
        # 2. Hand-verify against the recalculated INPUT cells (we recompute
        # from the same inputs the sheet uses, then compare to the sheet's
        # own recalculated outputs)
        # ------------------------------------------------------------------
        tgt_shares = read_ref(wb, refs["tgt_diluted_shares"])
        premium_pct = read_ref(wb, refs["offer_premium"])
        fee_pct = read_ref(wb, refs["transaction_fee_pct"])
        pct_cash = read_ref(wb, refs["pct_cash"])
        pct_debt = read_ref(wb, refs["pct_debt"])
        stepup_pct = read_ref(wb, refs["asset_step_up_pct"])
        amort_years = read_ref(wb, refs["intangible_amort_years"])
        tgt_assets = read_ref(wb, refs["tgt_total_assets"])
        tgt_liab = read_ref(wb, refs["tgt_total_liabilities"])

        exp_pev = tgt_price * (1 + premium_pct) * tgt_shares
        exp_fees = exp_pev * fee_pct
        exp_uses = exp_pev + exp_fees
        exp_cash = exp_uses * pct_cash
        exp_debt = exp_uses * pct_debt
        exp_stock = exp_uses - exp_cash - exp_debt
        exp_shares_issued = exp_stock / acq_price
        exp_book_equity = tgt_assets - tgt_liab
        exp_premium_over_book = exp_pev - exp_book_equity
        exp_stepup = exp_premium_over_book * stepup_pct
        exp_goodwill = exp_premium_over_book - exp_stepup
        exp_inc_da = exp_stepup / amort_years

        def close(a, b):
            if a is None or b is None:
                return False
            return abs(a - b) <= max(1e-6 * max(abs(a), abs(b)), 0.01)

        hand_checks = [
            ("purchase_equity_value", exp_pev),
            ("transaction_fees", exp_fees),
            ("total_uses", exp_uses),
            ("cash_used", exp_cash),
            ("new_debt", exp_debt),
            ("new_stock_issued", exp_stock),
            ("new_shares_issued", exp_shares_issued),
            ("tgt_book_equity", exp_book_equity),
            ("premium_over_book", exp_premium_over_book),
            ("asset_step_up", exp_stepup),
            ("goodwill", exp_goodwill),
            ("incremental_da", exp_inc_da),
        ]
        for key, expected in hand_checks:
            actual = read_ref(wb, refs[key])
            check(f"{acq_t}+{tgt_t} hand-verify {key}",
                  close(actual, expected),
                  f"sheet={actual!r} vs hand={expected!r}")

        print(f"  Goodwill: ${read_ref(wb, refs['goodwill'])/1e9:,.2f}B, "
              f"Incremental D&A: ${read_ref(wb, refs['incremental_da'])/1e6:,.1f}M/yr")

    print(f"\n{'='*70}")
    if failures:
        print(f"PHASE 3 TEST RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print(f"  - {f}")
    else:
        print("PHASE 3 TEST RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
