# Handoff: Deal Suite — institutional terminal redesign

## Overview

A visual redesign of Deal Suite (LBO Analyzer + M&A Modeler, both fed by SEC EDGAR filings).
The existing frontend is React 19 + Vite with a light-blue SaaS theme (`frontend/src/theme.css`).
This handoff replaces that visual layer with an institutional, data-first "terminal" treatment:
warm paper canvas, ink masthead, one gold accent, dense tabular decks, green/red reserved
exclusively for financial signs.

Nine frames are covered: three candidate app shells for the same filled LBO dashboard, then the
remaining product states drawn in the shell-A vocabulary.

## About the design files

`Deal Suite Mockup.dc.html` is a **design reference created in HTML** — a prototype showing intended
look and layout, not production code to copy. The task is to recreate these designs inside the
existing `frontend/` React + Vite codebase, using its component structure
(`src/lbo/components/*`, `src/ma/components/*`) and replacing the token layer in
`src/theme.css` / `src/suite.css` / `src/mna.css`.

The file is one static page containing all nine frames side by side on a pannable canvas. It has no
interactive behavior by design — every state is drawn out separately instead of being toggled.
`support.js` is the runtime that renders it; both files must sit in the same folder to open locally.

## Fidelity

**High fidelity.** Colors, type, spacing and copy are final. Numbers are placeholder financials and
company names are deliberately generic ("Placeholder Industrials, Inc.", TICKER-A / TICKER-B) —
replace with live data. Recreate the visual treatment closely; keep the real app's existing behavior,
routing and state.

## Screens / views

Frame ids match the badges in the HTML file.

### 1a — LBO filled, rail shell (recommended baseline)
- **Purpose**: the main working screen after a model is generated.
- **Layout**: 52px ink masthead → body flex row: 196px left rail (paper, 1px right hairline) +
  fluid main column (`padding: 20px 24px 26px`, `gap: 18px`).
- **Main column order**: ticker/company command row with three actions → 5-up KPI strip (single
  bordered card, 1px internal dividers) → 3-column grid (company snapshot / assumptions / ink
  returns-bridge card) → full-width debt schedule table (Y0–Y5) → 1.5fr/1fr row (sensitivity heatmap
  5×5 + feasibility checks).
- **Rail**: three labeled groups (Workspace / Model / Output). Active item has a 2px gold left border
  and `#f5edda` fill. Footer holds API status lines.

### 1b — LBO filled, masthead shell
No rail. Taller ink masthead carrying wordmark, subject, session state, and an underlined tab strip
(active tab = 2px gold bottom border). Below it a 5-up KPI ribbon at 34px figures, then a
1fr/340px body: sources & uses + projection table (with a small debt-balance bar row) on the left,
ink assumptions card + compact heatmap + provenance card on the right.

### 1c — LBO filled, workbench shell
Light 48px header. Fixed 312px left input column (subject, filed fundamentals, assumptions with
inline reference hints such as "Comp median 11.2×") against a `#f3f1ec` results canvas with a
sub-nav pill row, an ink 4-up summary band, a value-creation card with a stacked contribution bar,
feasibility checks, and a compact debt schedule.

### 1d — LBO empty / first run
Rail shell with disabled rail items. Left-aligned intro block (max 620px): gold eyebrow
"Step 01 — subject company", 27px headline, 13.5px supporting paragraph, ticker field + Analyze
button, then a 3-up method strip (Pull / Model / Export) and an empty "Recent runs" panel.

### 1e — Loading / cold start
Amber banner (`#faf1e2` on `#e8d4a8`) explaining the ~20s cold start with an elapsed counter, a 3px
gold progress bar at 34%, three skeleton cards plus one wide skeleton, and a step trail line.

### 1f — M&A deal builder, generated
Acquirer + target cards separated by a gold `+`, then Generate. 5-up KPI strip (Yr 1 EPS impact,
premium, consideration mix, pro forma leverage, post-deal HHI). Sources & uses + purchase price
allocation side by side, a full-width pro forma income statement with an EPS accretion row
(highlighted `#f8f6f1`), then HHI bar chart + 4×4 EPS sensitivity grid.

### 1g — M&A validation failure
Red banner (1 blocking, 3 warnings) with a disabled Generate button, then a five-column validation
log (severity badge, field, finding, source, action) and three summary counters.

### 1h — Comparison
Six-row metric table across three saved cases with a spread column; Case A column tinted
`#f8f6f1`. Below: ink narrative-report card (LLM commentary, draft disclaimers) + IRR-by-case bar
card.

### 1i — Settings modal
Blurred page behind a `rgba(20,22,26,.34)` scrim. 520px modal, ink title bar reading
"Add API key for AI analysis", amber session-scope disclosure, 3-way provider segmented control
(Anthropic / OpenAI / Google), masked key field showing "Added for this session", SEC contact email
field, and Clear key / Cancel / Save for session actions.

## Interactions & behavior

Preserve the current app's behavior; the redesign changes only presentation.

- Product switcher (LBO / M&A) drives `/lbo` and `/ma` as today; both panes stay mounted.
- Tabs: Model builder / Comparison (Comparison shows a count badge once models exist).
- Phases: `empty → loading → ready → generated`, matching `useAppState` / `useDealState`.
- Cold start: show the amber wake banner while `useBackendWake` reports waking; progress bar and
  step trail are indicative, not measured.
- Validation: a blocking issue disables Generate; warnings are acceptable and must be carried into
  the workbook provenance sheet.
- Provenance badges (Filed / Defaulted / Substituted / User / Assumption) render inline next to the
  value they describe.
- All control labels must be `white-space: nowrap`; several labels ("M&A Modeler", "Save for
  session", "Debt schedule") wrap and break the layout otherwise.
- Transitions: 150ms ease for hover, 200ms for state changes. No decorative motion.

## State management

Unchanged from the current implementation: `product`, `activeTab`, `phase`, `tickerInput`,
`snapshot`, `assumptions` + `assumptionMeta`, `userOverrides`, `results`, `sensitivity`,
`savedModels`, `toast`, `settingsOpen`, and session keys (`llmProvider`, `llmApiKey`) held in
`sessionStorage` only.

## Design tokens

Colors
```
--canvas          #f3f1ec   page canvas
--canvas-alt      #eae7e0   outer/desk background
--paper           #fcfbf9   cards, rail, inputs
--paper-alt       #f8f6f1   table emphasis rows, sub-nav bar
--ink             #14161a   masthead, primary text, dark cards
--ink-2           #23272e   secondary text on light
--ink-line        #2c3138   hairlines inside ink surfaces
--text-muted      #5c6067   body labels
--text-dim        #7b7f86   tertiary
--text-faint      #9ea1a7   eyebrow labels, metadata
--hairline        #e3e0d9   card borders
--hairline-soft   #eeece6   internal dividers
--row-line        #f2f0ea   table row rules
--field-border    #d6d2c9   secondary buttons, inputs
--gold            #a8792c   single accent (active states, marks, base-case cell)
--gold-soft       #f5edda   active nav fill, disclosure panels
--gold-mid        #c9b98c   chart mid tone
--gold-pale       #dfd9c8   chart light tone
--gold-on-ink     #d3ab60   accent text on ink
--positive        #1f6f4a   /  on ink #7ec59f
--positive-bg     #e6efe9   scale: #f0f5f1 #e6efe9 #dbeae1 #cfe3d7 #c2dccd
--negative        #a83232   /  on ink #e79a94
--negative-bg     #f6e8e6
--warning         #96631a
--warning-bg      #faf1e2   border #e8d4a8
--input-value     #1d4ed8   user-editable numeric values
```

Typography
```
UI + numerals   'Instrument Sans', system-ui, sans-serif
Wordmark        'Pinyon Script', cursive   (27px in the 52px masthead, 32px in 1b, 26px on light)
Figures         tabular: body { font-variant-numeric: tabular-nums }

Eyebrow label   600 10px / 1, letter-spacing .045em, #9ea1a7   (sentence case)
Card title      600 10.5px / 1, letter-spacing .045em, #14161a
KPI figure      500 27px / 1 (34px in 1b, 30px in 1c)
Table header    600 9px–10px / 1, letter-spacing .045em, #9ea1a7
Table cell      400 12px (label) · 500 12px (numeric)
Nav item        400 12.5px / 1 · active 600
Button          600 11px / 1, nowrap
Body copy       400 12–13.5px, line-height 1.55–1.7, text-wrap: pretty
```

Spacing / geometry
```
Card padding     12px 16px (header) · 14–20px (body)
Grid gaps        16px within a screen, 18px between stacked decks
Table cell       9px 16px  (11px 18px in comparison / validation)
Radii            0 everywhere — squared corners are part of the look
Borders          1px hairlines; 2px gold for active nav; no shadows except the modal
Modal shadow     0 18px 48px rgba(20,22,26,.22)
Marks            9px gold square rotated 45° (the diamond beside the wordmark)
```

Type rules that matter: sentence case for all labels (no wide-tracked caps), acronyms stay upper
(IRR, EBITDA, DSCR, HHI, EPS, XBRL, SEC, EDGAR, USD, SOFR, CIK), units lowercase (mm, bps, yrs, pts).

## Assets

No image or icon assets. Every graphic is CSS: the rotated gold diamond, heatmap cells, bar charts,
skeleton blocks, status dots. Fonts come from Google Fonts (Instrument Sans, Pinyon Script; Newsreader
is loaded but no longer used and can be dropped). No user-facing emoji.

## Files

```
Deal Suite Mockup.dc.html   all nine frames (1a–1i); frame ids are visible badges in the file
support.js                  runtime required to open the HTML locally
screens/                    2x PNG of each frame, one file per frame:
                              1a-lbo-filled-rail-shell.png
                              1b-lbo-filled-masthead-shell.png
                              1c-lbo-filled-workbench-shell.png
                              1d-lbo-empty-state.png
                              1e-loading-cold-start.png
                              1f-ma-deal-builder-filled.png
                              1g-ma-validation-warnings.png
                              1h-comparison.png
                              1i-settings-api-key.png
```

Existing code the redesign maps onto:
```
frontend/src/App.tsx                     shell, product switcher, settings entry
frontend/src/theme.css                   token layer to replace
frontend/src/lbo/App.tsx + components/   1a–1e, 1h (LBO)
frontend/src/ma/App.tsx  + components/   1f, 1g, 1h (M&A)
frontend/src/ma/components/SettingsModal.tsx   1i
```
