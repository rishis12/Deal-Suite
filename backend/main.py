"""Deal Suite API — one service hosting both product backends.

The LBO Analyzer (AIO LBO) app is mounted at /lbo and the M&A Modeler app
at /ma, each with its original routes, CORS middleware, and rate limiting
intact (e.g. /lbo/analyze, /ma/generate). One service means one Render
instance, one cold start, and one LibreOffice-bearing image instead of two.

Mounted Starlette sub-apps do not get their lifespans run automatically,
so this wrapper enters both sub-app lifespan contexts itself.
"""

from contextlib import AsyncExitStack, asynccontextmanager

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
