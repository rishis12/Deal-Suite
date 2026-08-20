"""Deal Suite API — one service hosting both product backends.

The LBO Analyzer (AIO LBO) app is mounted at /lbo and the M&A Modeler app
at /ma, each with its original routes, CORS middleware, and rate limiting
intact (e.g. /lbo/analyze, /ma/generate). One service means one Render
instance, one cold start, and one LibreOffice-bearing image instead of two.

Mounted Starlette sub-apps do not get their lifespans run automatically,
so this wrapper enters both sub-app lifespan contexts itself.
"""

import os
import re
from contextlib import AsyncExitStack, asynccontextmanager

# ---------------------------------------------------------------------------
# Environment sanitizer — MUST run before the product apps import their config.
#
# In deployed environments, env vars have been observed carrying fragments of
# the start command ("main:app", "--host") instead of their real values. Each
# setting below is validated by SHAPE, tried across several variable names
# (the DEAL_SUITE_* aliases exist so a fresh, unclobbered name can always be
# used), cleaned, and written back so both sub-apps read sane values.
# ---------------------------------------------------------------------------


def _resolve(names: list[str], is_valid, clean=lambda v: v) -> str:
    for name in names:
        raw = os.environ.get(name, "").strip().strip('"').strip("'")
        if not raw:
            continue
        if raw.startswith("--") or raw in ("uvicorn", "main:app", "api:app"):
            print(f"[ENV] {name} looks like a command fragment ({raw!r}) — ignored")
            continue
        if is_valid(raw):
            return clean(raw)
        print(f"[ENV] {name} failed shape validation ({raw!r}) — ignored")
    return ""


_email = _resolve(
    ["DEAL_SUITE_SEC_EMAIL", "SEC_CONTACT_EMAIL"],
    lambda v: "@" in v and "." in v.split("@")[-1] and ":" not in v and " " not in v,
)
_twelve = _resolve(
    ["DEAL_SUITE_TWELVE_KEY", "TWELVE_DATA_API_KEY"],
    lambda v: re.fullmatch(r"[A-Za-z0-9]{16,64}", v) is not None,
)
_frontend = _resolve(
    ["DEAL_SUITE_FRONTEND_URL", "FRONTEND_URL"],
    lambda v: v.startswith("http"),
    # Browsers send Origin without a trailing slash; CORS matches exactly.
    clean=lambda v: ",".join(o.strip().rstrip("/") for o in v.split(",") if o.strip()),
)

os.environ["SEC_CONTACT_EMAIL"] = _email
os.environ["TWELVE_DATA_API_KEY"] = _twelve
os.environ["FRONTEND_URL"] = _frontend
print(f"[ENV] resolved SEC_CONTACT_EMAIL: {_email!r}")
print(f"[ENV] resolved TWELVE_DATA_API_KEY: {'set (' + _twelve[:4] + '…)' if _twelve else '(not set)'}")
print(f"[ENV] resolved FRONTEND_URL: {_frontend!r}")

from fastapi import FastAPI

from lbo.api import app as lbo_app
from ma.api import app as ma_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(lbo_app.router.lifespan_context(lbo_app))
        await stack.enter_async_context(ma_app.router.lifespan_context(ma_app))
        yield


app = FastAPI(
    title="Deal Suite API",
    description="LBO and M&A modeling from SEC filings — /lbo/* and /ma/*",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/lbo", lbo_app)
app.mount("/ma", ma_app)


@app.get("/health")
def health():
    """Suite-level liveness. Product-level config detail lives at
    /lbo/health and /ma/health (which the frontend wake-pings use)."""
    return {"status": "ok", "products": ["/lbo", "/ma"]}
