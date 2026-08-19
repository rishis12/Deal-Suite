# Test drives — two real deal setups

Both examples below were verified against live SEC data (August 2026). They
exercise sheet generation, the HHI concentration tab, provenance flags, and
both comparison modes. Expected numbers will drift as new filings and prices
come in — treat them as landmarks, not gospel.

## Example 1 — Union Pacific acquires Norfolk Southern (UNP → NSC)

The real thing: UP announced its ~$85B merger with Norfolk Southern in
July 2025 (all-stock, ~18.5% premium). The model lets you see *why* it had
to be all-stock.

**Generate (scenario A — default financing):** analyze `UNP` → `NSC`,
generate with defaults (25% premium, 40% cash / 30% debt).
Expect: purchase equity value ≈ $97B, Year-1 EPS **dilution around −45%**,
still dilutive in Year 5. Financing a railroad mega-merger with $39B of
cash and $29B of 8% debt shreds EPS.

**Generate (scenario B — the real structure):** set Offer Premium to
`18.5`, % Cash `0`, % Debt `0` (all-stock, the derived % Stock shows 100%).
Expect Year-1 dilution to improve to about **−28%** — still deeply dilutive
because the 50% asset step-up generates billions in incremental D&A, which
is exactly why the real deal leans on long-term synergy claims.

**Market concentration:** both are SIC 4011 (Class I railroads — the table
pre-fills both names). Enter roughly UNP `30`, NSC `20`, BNSF Railway `30`,
CSX `20`. Expect ΔHHI = 1,200 on a post-merger HHI near 3,800 —
**"presumed likely to enhance market power"**, matching the real deal's
regulatory drama. (The narrative report will still refuse to predict the
outcome — that's by design.)

**Provenance demo:** NSC's total debt is missing from its latest XBRL facts,
so the validator degrades politely and the workbook carries a yellow
defaulted-to-$0 flag instead of failing.

**Comparison (Mode A):** compare the two saved UNP/NSC scenarios. Only
% Cash / % Debt (and premium) differ — the tool's causal-commentary
exception applies to the financing-mix change.

## Example 2 — Home Depot acquires Lowe's (HD → LOW)

The perennial "what if" — two SIC 5211 big-box rivals, target trading at a
cheaper P/E (~19 vs ~24), $154B purchase equity value.

**Generate (scenario A — no synergies):** analyze `HD` → `LOW`, generate
with defaults. Expect Year-1 **−21%** improving to **−8%** by Year 5 —
dilutive throughout. Even buying cheaper earnings can't outrun step-up
D&A plus financing costs at this scale.

**Generate (scenario B — the synergy case):** set Cost Synergies to `4`
(keep the 3-year ramp). Expect **−7.5% in Year 1, crossing to accretive in
Year 2 (+10%), reaching ~+38% by Year 5** — the classic crossover story,
stated deterministically by the crossover line under the chart.

**Market concentration:** same-SIC pre-fill again. Try HD `17`, LOW `11`,
Menards `4`, Ace Hardware `4` (broad home-improvement market) — a large
ΔHHI in an unconcentrated market, i.e. flagged differently than the
railroad case. Use "Copy research prompt" to source better estimates.

**Comparison (Mode A):** the two HD/LOW scenarios differ only in cost
synergies — a single-field diff, so causal commentary is allowed.

## Cross-deal comparison (Mode B)

Compare any saved UNP/NSC model against any saved HD/LOW model. Expect the
"Deal A (UNP acquiring NSC) vs Deal B (HD acquiring LOW)" framing with the
full side-by-side assumptions table and no causal attribution between deals.

Also worth trying: download each model's Excel and re-upload it in a
comparison slot — the hidden `_refs` sheet makes standalone files
comparable without any session state.
