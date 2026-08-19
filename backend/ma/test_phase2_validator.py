"""
Phase 2 test: M&A pair validator.

1. Live validation across the Phase 1 varied ticker set.
2. Sector exclusion tested in BOTH positions (excluded company as acquirer,
   and as target).
3. Loss-making company confirmed NOT hard-failed on negative net income
   (the deliberate divergence from AIO LBO).
4. Synthetic deterministic checks of the hard/soft/default rules.

Prices are injected synthetically ($100) for live profiles since no Twelve
Data key is available in the test environment — the missing-price hard
requirement is exercised separately in the synthetic section.
"""

import copy
from . import data_layer as dl
from .validator import validate_company, validate_pair, format_pair_validation

LIVE_TICKERS = [
    # Phase 1 varied set (subset)
    "AAPL", "MSFT", "JNJ", "CROX", "POOL", "FIZZ", "CCL", "AAL", "TSLA", "BRK.B",
    # Excluded sectors
    "JPM",   # bank (SIC 6022)
    "DUK",   # utility (SIC 4911)
    # Loss-making candidates (verify NI < 0 at runtime)
    "PTON", "RDDT",
]

failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(f"{name}: {detail}")


def make_pair(profiles, acq, tgt):
    a = copy.deepcopy(profiles[acq])
    t = copy.deepcopy(profiles[tgt])
    a["role"], t["role"] = "acquirer", "target"
    return {"acquirer": a, "target": t,
            "fetch_status": {"acquirer": "OK", "target": "OK"}}


def main():
    ua = dl.get_sec_user_agent()

    print(f"Fetching {len(LIVE_TICKERS)} companies...")
    profiles = {}
    for i, ticker in enumerate(LIVE_TICKERS, 1):
        p = dl.fetch_company(ticker, ua, verbose=False, skip_price=True)
        if p is None:
            print(f"  [{i}/{len(LIVE_TICKERS)}] {ticker}: FETCH FAILED")
            continue
        p["current_price"] = 100.0  # synthetic price (no Twelve Data key here)
        p["current_price_source"] = "synthetic-test"
        profiles[ticker] = p
        fy = max(p["fiscal_years"]) if p["fiscal_years"] else None
        ni = p["fiscal_years"][fy]["net_income"] if fy else None
        print(f"  [{i}/{len(LIVE_TICKERS)}] {ticker}: OK "
              f"(FY{fy}, NI {'%.0fM' % (ni/1e6) if ni is not None else 'MISSING'})")

    # ------------------------------------------------------------------
    print(f"\n{'='*70}\n1. NORMAL PAIRS — should never FAIL\n{'='*70}")
    normal_pairs = [("AAPL", "CROX"), ("MSFT", "POOL"), ("JNJ", "FIZZ"),
                    ("CCL", "AAL"), ("TSLA", "SMPL" if "SMPL" in profiles else "FIZZ")]
    for acq, tgt in normal_pairs:
        if acq not in profiles or tgt not in profiles:
            continue
        v = validate_pair(make_pair(profiles, acq, tgt))
        check(f"{acq}+{tgt} not fail", v["status"] != "fail",
              f"status={v['status']}" +
              (f", reasons={v['disqualifying_reasons']}" if v["status"] == "fail" else ""))

    # ------------------------------------------------------------------
    print(f"\n{'='*70}\n2. SECTOR EXCLUSION — both positions\n{'='*70}")
    for excluded in ("JPM", "DUK"):
        if excluded not in profiles:
            continue
        # Excluded company as ACQUIRER
        v = validate_pair(make_pair(profiles, excluded, "AAPL"))
        check(f"{excluded} as acquirer fails pair", v["status"] == "fail",
              f"status={v['status']}")
        check(f"{excluded} acquirer sub-verdict sector_excluded",
              v["acquirer"]["sector_excluded"])
        check(f"{excluded}-as-acquirer reason references acquirer",
              any("ACQUIRER" in r for r in v["disqualifying_reasons"]),
              str(v["disqualifying_reasons"]))
        # Excluded company as TARGET
        v = validate_pair(make_pair(profiles, "AAPL", excluded))
        check(f"{excluded} as target fails pair", v["status"] == "fail",
              f"status={v['status']}")
        check(f"{excluded} target sub-verdict sector_excluded",
              v["target"]["sector_excluded"])
        check(f"{excluded}-as-target reason references target",
              any("TARGET" in r for r in v["disqualifying_reasons"]),
              str(v["disqualifying_reasons"]))

    # ------------------------------------------------------------------
    print(f"\n{'='*70}\n3. LOSS-MAKING COMPANY — the deliberate LBO divergence\n{'='*70}")
    loss_makers = []
    for ticker, p in profiles.items():
        if not p["fiscal_years"]:
            continue
        fy = max(p["fiscal_years"])
        ni = p["fiscal_years"][fy]["net_income"]
        if ni is not None and ni < 0:
            loss_makers.append((ticker, fy, ni))
    print(f"  Companies with negative most-recent NI: "
          f"{[(t, f'FY{fy}', f'{ni/1e6:,.0f}M') for t, fy, ni in loss_makers]}")
    check("at least one loss-maker in live set", len(loss_makers) > 0,
          "need a company with recent net loss to exercise the divergence")

    for ticker, fy, ni in loss_makers:
        for role, pair_def in [("target", ("MSFT", ticker)), ("acquirer", (ticker, "MSFT"))]:
            v = validate_pair(make_pair(profiles, *pair_def))
            sub = v[role]
            ni_in_disqualifying = any(
                "net income" in r.lower() or "ebitda" in r.lower()
                for r in sub["disqualifying_reasons"])
            check(f"{ticker} as {role}: NI/EBITDA not disqualifying",
                  not ni_in_disqualifying, str(sub["disqualifying_reasons"]))
            check(f"{ticker} as {role}: negative-NI warning present",
                  any("et income" in w for w in sub["warnings"]),
                  str(sub["warnings"]))
            check(f"{ticker} as {role}: pair not failed by loss alone",
                  v["status"] != "fail" or ni_in_disqualifying is False,
                  f"status={v['status']}, reasons={v['disqualifying_reasons']}")

    # ------------------------------------------------------------------
    print(f"\n{'='*70}\n4. SYNTHETIC DETERMINISTIC CHECKS\n{'='*70}")

    def synth_profile(**overrides):
        fy_data = {
            "fiscal_year": 2025, "missing": [],
            "revenue": 1_000e6, "operating_income": 200e6, "da": 50e6,
            "net_income": 150e6, "diluted_eps": 1.50, "diluted_shares": 100e6,
            "total_assets": 2_000e6, "total_liabilities": 1_200e6,
            "ebitda_calculated": 250e6, "total_debt": 300e6, "cash": 100e6,
            "capex": 40e6,
        }
        profile = {
            "ticker": "SYN", "company_name": "Synthetic Corp", "cik": 1,
            "sic_code": "2080", "sic_description": "Beverages",
            "current_price": 50.0, "shares_outstanding": 100e6,
            "diluted_shares": 100e6, "substitute_flags": {}, "tag_matches": {},
            "fiscal_years": {2025: fy_data}, "missing_fields": [],
        }
        for k, val in overrides.items():
            if k in fy_data:
                fy_data[k] = val
            else:
                profile[k] = val
        return profile

    v = validate_company(synth_profile())
    check("clean synthetic passes", v["status"] == "pass", v["status"])

    v = validate_company(synth_profile(revenue=None))
    check("1 hard missing -> degraded", v["status"] == "degraded", v["status"])

    v = validate_company(synth_profile(revenue=None, net_income=None))
    check("2 hard missing -> fail", v["status"] == "fail", v["status"])

    v = validate_company(synth_profile(current_price=None))
    check("missing price -> degraded (hard)", v["status"] == "degraded"
          and any("price" in m.lower() for m in v["missing_hard"]), v["status"])

    p = synth_profile(diluted_eps=None)
    v = validate_company(p)
    check("EPS missing but shares present -> still pass",
          v["status"] == "pass", v["status"])

    p = synth_profile(diluted_eps=None, diluted_shares=None)
    p["diluted_shares"] = None
    p["shares_outstanding"] = None
    v = validate_company(p)
    check("no EPS and no share count -> hard missing", v["status"] == "degraded"
          and any("per-share" in m for m in v["missing_hard"]), str(v["missing_hard"]))

    v = validate_company(synth_profile(total_debt=None, cash=None, capex=None))
    check("soft missing -> degraded with 3 defaults",
          v["status"] == "degraded" and len(v["defaults_applied"]) == 3,
          f"{v['status']}, defaults={len(v['defaults_applied'])}")

    v = validate_company(synth_profile(total_assets=None))
    check("assets missing -> goodwill_precision_degraded, not fail",
          v["status"] == "degraded" and v["goodwill_precision_degraded"],
          v["status"])

    v = validate_company(synth_profile(net_income=-500e6, ebitda_calculated=-100e6))
    check("negative NI+EBITDA alone -> degraded, NEVER fail",
          v["status"] == "degraded" and not v["disqualifying_reasons"],
          f"{v['status']}, reasons={v['disqualifying_reasons']}")

    v = validate_company(synth_profile(sic_code="6022"))
    check("bank SIC -> fail + sector_excluded",
          v["status"] == "fail" and v["sector_excluded"], v["status"])

    v = validate_company(None)
    check("None profile -> fail", v["status"] == "fail", v["status"])

    stale = synth_profile()
    stale["fiscal_years"] = {2022: stale["fiscal_years"][2025]}
    v = validate_company(stale)
    check("stale (FY2022) -> fail", v["status"] == "fail", v["status"])

    # ------------------------------------------------------------------
    print(f"\n{'='*70}\nSample formatted output (MSFT + loss-maker)\n{'='*70}")
    if loss_makers:
        print(format_pair_validation(
            validate_pair(make_pair(profiles, "MSFT", loss_makers[0][0]))))

    print(f"\n{'='*70}")
    if failures:
        print(f"PHASE 2 TEST RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print(f"  - {f}")
    else:
        print("PHASE 2 TEST RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
