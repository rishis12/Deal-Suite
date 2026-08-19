"""
Phase 1 test: two-company fetch layer against a varied ticker set.

Reuses a subset of AIO LBO's 20-ticker stress test set (large-cap, mid-cap,
debt-heavy, COVID-distorted) paired up as acquirer/target. Confirms:
1. Net Income, Diluted EPS, Diluted Shares, Total Assets/Liabilities resolve
   (or flag MISSING) across the set, with a tag-usage frequency table
2. Two-ticker fetch does not cross-contaminate data between companies
3. Rate limiting holds under the doubled SEC call volume
"""

import time
from . import data_layer as dl

# Subset of AIO LBO's proven 20-ticker stress set, paired for M&A testing.
# Categories: large-cap, mid-cap, small-cap, debt-heavy, COVID-distorted
# (CCL/AAL both had severe COVID-era distortion), edge-case (BRK.B, TSLA).
TEST_PAIRS = [
    ("AAPL", "CROX"),   # large-cap acquirer, mid-cap target
    ("MSFT", "WING"),   # large-cap acquirer, small-cap target
    ("JNJ",  "SMPL"),   # large-cap acquirer, small-cap target
    ("CCL",  "AAL"),    # both debt-heavy AND COVID-distorted
    ("BRK.B", "POOL"),  # dot-ticker edge case acquirer, mid-cap target
    ("TSLA", "DECK"),   # edge-case reporting acquirer, mid-cap target
    ("POOL", "FIZZ"),   # mid-cap acquirer, small-cap target
]

NEW_CONCEPTS = ["net_income", "diluted_eps", "diluted_shares",
                "total_assets", "total_liabilities"]


def instrument_rate_limiter():
    """Wrap fetch_sec_endpoint to record request timestamps."""
    timestamps = []
    original = dl.fetch_sec_endpoint

    def wrapped(url, user_agent):
        timestamps.append(time.time())
        return original(url, user_agent)

    dl.fetch_sec_endpoint = wrapped
    return timestamps


def main():
    sec_user_agent = dl.get_sec_user_agent()
    print(f"SEC User-Agent: {sec_user_agent}")

    timestamps = instrument_rate_limiter()

    all_profiles = {}   # ticker -> profile
    pair_results = []
    failures = []

    print(f"\nFetching {len(TEST_PAIRS)} acquirer/target pairs "
          f"({len(set(t for p in TEST_PAIRS for t in p))} distinct tickers)...")

    for i, (acq, tgt) in enumerate(TEST_PAIRS, 1):
        print(f"\n[{i}/{len(TEST_PAIRS)}] Pair: {acq} (acquirer) + {tgt} (target)")
        pair = dl.fetch_ma_pair(acq, tgt, verbose=False, skip_price=True)
        pair_results.append((acq, tgt, pair))

        for role, ticker in [("acquirer", acq), ("target", tgt)]:
            status = pair["fetch_status"][role]
            profile = pair[role]
            if status != "OK" or profile is None:
                failures.append(f"{ticker} ({role} in pair {acq}/{tgt})")
                print(f"  {role} {ticker}: FAILED")
            else:
                all_profiles[ticker] = profile
                fy_count = len(profile["fiscal_years"])
                print(f"  {role} {ticker}: OK ({profile['company_name']}, "
                      f"{fy_count} fiscal years)")

    # ------------------------------------------------------------------
    # CHECK 1: New-concept tag usage frequency table
    # ------------------------------------------------------------------
    print(f"\n{'='*80}")
    print("CHECK 1: TAG USAGE FREQUENCY - NEW M&A CONCEPTS")
    print(f"{'='*80}")

    for concept in NEW_CONCEPTS:
        print(f"\n--- {concept.upper()} ---")
        tag_to_tickers = {}
        for ticker, profile in all_profiles.items():
            tag = profile["tag_matches"].get(concept, "?")
            tag_to_tickers.setdefault(tag, []).append(ticker)
        for tag, tickers in sorted(tag_to_tickers.items(),
                                   key=lambda x: len(x[1]), reverse=True):
            print(f"  {tag}: {len(tickers)} companies ({', '.join(sorted(tickers))})")

    print(f"\n--- Per-ticker most-recent-FY values for new concepts ---")
    header = f"{'Ticker':<8}" + "".join(f"{c:<20}" for c in NEW_CONCEPTS)
    print(header)
    for ticker, profile in sorted(all_profiles.items()):
        fys = sorted(profile["fiscal_years"].keys(), reverse=True)
        row = f"{ticker:<8}"
        if fys:
            d = profile["fiscal_years"][fys[0]]
            for c in NEW_CONCEPTS:
                v = d.get(c)
                if v is None:
                    cell = "MISSING"
                elif c == "diluted_eps":
                    cell = f"{v:.2f}"
                elif c == "diluted_shares":
                    cell = f"{v/1e6:,.0f}M sh"
                else:
                    cell = f"${v/1e9:,.2f}B"
                row += f"{cell:<20}"
        else:
            row += "NO FY DATA"
        print(row)

    # ------------------------------------------------------------------
    # CHECK 2: Cross-contamination between the two companies in one call
    # ------------------------------------------------------------------
    print(f"\n{'='*80}")
    print("CHECK 2: CROSS-CONTAMINATION (AAPL vs CROX pair, field-by-field)")
    print(f"{'='*80}")

    acq, tgt, pair = pair_results[0]
    a, t = pair["acquirer"], pair["target"]
    contamination = []

    if a and t:
        checks = [
            ("ticker", a["ticker"], "AAPL"), ("ticker", t["ticker"], "CROX"),
            ("cik", a["cik"], 320193), ("cik", t["cik"], 1334036),
        ]
        for name, actual, expected in checks:
            ok = actual == expected
            print(f"  {name}: {actual} (expected {expected}) -> {'OK' if ok else 'MISMATCH'}")
            if not ok:
                contamination.append(f"{name}: {actual} != {expected}")

        if "Apple" not in a["company_name"]:
            contamination.append(f"acquirer name: {a['company_name']}")
        if "Crocs" not in t["company_name"]:
            contamination.append(f"target name: {t['company_name']}")
        print(f"  acquirer name: {a['company_name']}")
        print(f"  target name:   {t['company_name']}")

        # Magnitude check: AAPL revenue ~$390B+, CROX ~$4B. If swapped or
        # contaminated, these would be wildly off.
        a_fy = max(a["fiscal_years"].keys())
        t_fy = max(t["fiscal_years"].keys())
        a_rev = a["fiscal_years"][a_fy]["revenue"]
        t_rev = t["fiscal_years"][t_fy]["revenue"]
        print(f"  AAPL FY{a_fy} revenue: ${a_rev/1e9:,.1f}B (expect > $200B)")
        print(f"  CROX FY{t_fy} revenue: ${t_rev/1e9:,.1f}B (expect < $10B)")
        if not (a_rev > 200e9):
            contamination.append(f"AAPL revenue implausible: {a_rev}")
        if not (t_rev < 10e9):
            contamination.append(f"CROX revenue implausible: {t_rev}")

        # Every fiscal-year record in each profile must carry only that
        # company's data: check no shared object references between profiles.
        shared = set(map(id, a["fiscal_years"].values())) & \
                 set(map(id, t["fiscal_years"].values()))
        print(f"  Shared fiscal-year object references: {len(shared)}")
        if shared:
            contamination.append("profiles share fiscal-year objects")

        print(f"\n  CHECK 2 RESULT: {'PASS - no cross-contamination' if not contamination else 'FAIL: ' + '; '.join(contamination)}")
    else:
        print("  FAIL: AAPL/CROX pair did not fetch")

    # ------------------------------------------------------------------
    # CHECK 3: Rate limiting under doubled load
    # ------------------------------------------------------------------
    print(f"\n{'='*80}")
    print("CHECK 3: SEC RATE LIMITING UNDER TWO-COMPANY LOAD")
    print(f"{'='*80}")

    print(f"  Total SEC requests made: {len(timestamps)}")
    max_in_any_second = 0
    for i in range(len(timestamps)):
        count = sum(1 for t2 in timestamps if timestamps[i] <= t2 < timestamps[i] + 1.0)
        max_in_any_second = max(max_in_any_second, count)
    print(f"  Max requests in any rolling 1-second window: {max_in_any_second}")
    print(f"  SEC limit: 10/sec -> {'PASS' if max_in_any_second <= 10 else 'FAIL'}")

    if len(timestamps) > 1:
        gaps = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
        print(f"  Min gap between consecutive requests: {min(gaps)*1000:.0f}ms "
              f"(configured delay: {dl.SEC_REQUEST_DELAY*1000:.0f}ms)")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*80}")
    print("PHASE 1 TEST SUMMARY")
    print(f"{'='*80}")
    print(f"  Pairs fetched: {len(pair_results)}")
    print(f"  Distinct companies: {len(all_profiles)}")
    print(f"  Fetch failures: {failures if failures else 'none'}")

    missing_by_ticker = {}
    for ticker, profile in all_profiles.items():
        genuinely_missing = [c for c in NEW_CONCEPTS
                             if profile["tag_matches"].get(c) == "MISSING"]
        if genuinely_missing:
            missing_by_ticker[ticker] = genuinely_missing
    if missing_by_ticker:
        print("  Companies with MISSING new concepts (all fallbacks exhausted):")
        for ticker, concepts in missing_by_ticker.items():
            print(f"    {ticker}: {', '.join(concepts)}")
    else:
        print("  All new concepts resolved for every company (no MISSING).")


if __name__ == "__main__":
    main()
