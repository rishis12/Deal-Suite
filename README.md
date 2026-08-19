# Deal Suite

One site, two deal-modeling products, built from live SEC filings:

- **LBO Analyzer** — leveraged-buyout modeling for a single company: entry/exit
  multiples, debt schedule, feasibility scoring, sensitivity heatmap.
- **M&A Modeler** — two-company accretion/dilution analysis: sources & uses,
  purchase price allocation, pro forma income statement, EPS accretion/dilution
  by year, market concentration (HHI), and a sensitivity grid.

Both produce a fully-formulated, downloadable Excel model (no hardcoded
results — every number is a live formula, verified by real recalculation),
support saved-model comparison, and can generate an AI narrative report with
your own LLM key (Anthropic, OpenAI, or Google — BYOK, session-only, never
stored server-side).

## Architecture

```
frontend/          React 19 + Vite + TypeScript (Vercel)
  src/App.tsx      Shell: header, /lbo | /ma product routing, shared BYOK store
  src/lbo/         LBO Analyzer pane (from AIO LBO)
  src/ma/          M&A Modeler pane (from MNA-noMBA)
backend/           FastAPI, one service (Render/Docker)
  main.py          Mounts both product APIs: /lbo/* and /ma/*
  lbo/             AIO LBO backend package
  ma/              M&A backend package
```

One backend service hosts both product APIs — one container, one cold start.
Each sub-app keeps its original routes, CORS, and rate limiting under its
prefix (e.g. `POST /ma/analyze`, `POST /lbo/generate`).

## Local development

Backend (needs Python 3.11+, and LibreOffice or Excel for recalculation):

```
cd backend
pip install -r requirements.txt
set SEC_CONTACT_EMAIL=you@example.com        # SEC requires a real contact
set TWELVE_DATA_API_KEY=...                  # optional; prices degrade gracefully
python -m uvicorn main:app --port 8002
```

Or in Docker: `SEC_CONTACT_EMAIL=you@example.com docker compose up --build`

Frontend:

```
cd frontend
npm install
npm run dev          # http://localhost:5200, expects the API on :8002
```

Tests (the M&A phase suites; run from `backend/`):

```
python -m ma.test_phase2_validator
python -m ma.test_phase4_proforma    # includes real workbook recalculation
```

## Deployment

- **Backend** — deploy `backend/` as a Docker web service (e.g. Render).
  Env vars: `SEC_CONTACT_EMAIL` (required), `TWELVE_DATA_API_KEY` (optional),
  `FRONTEND_URL` (your frontend origin — locks down CORS; without it the API
  allows all origins, which is for local dev only). The platform's `PORT` is
  honored automatically.
- **Frontend** — deploy `frontend/` to Vercel. Set `VITE_API_URL` to the
  backend's URL. `vercel.json` already rewrites `/lbo` and `/ma` to the SPA.

## Keys and privacy

- LLM API keys are **bring-your-own**: entered in the UI, kept in
  `sessionStorage` for the browser session only, sent only with the requests
  they authorize, and never logged or persisted by the backend.
- No server-side secrets live in this repo. Local launcher scripts holding
  personal keys are gitignored by name.
