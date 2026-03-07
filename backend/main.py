# to run: uvicorn main:app --reload --port 8000

# download these packages
# pip install fastapi uvicorn httpx python-dotenv shapely h3 geopandas pandas numpy supabase psycopg2-binary pydantic

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from dotenv import load_dotenv

load_dotenv()

from routers import ingestion

# ── Routers ──────────────────────────────────────────────────────────────────
# Uncomment each router as you build it out
# from routers import ingestion, hazard, scoring, optimizer



# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wildroute")


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once on startup and once on shutdown.
    Use this to warm up DB connections, pre-fetch static data, etc.
    """
    logger.info("WildRoute API starting up...")

    # TODO: initialise Supabase connection pool
    # TODO: pre-fetch static road closure data (changes infrequently)
    # TODO: warm H3 index cache if needed

    yield  # <── app is live and serving requests here

    logger.info("WildRoute API shutting down...")
    # TODO: close DB connections cleanly


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="WildRoute API",
    description=(
        "Wildfire-aware routing engine. "
        "Ingests NASA FIRMS, Environment Canada, and AQI data, "
        "generates smoke-dispersion hazard fields, and scores / optimises routes."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",       # Swagger UI  → http://localhost:8000/docs
    redoc_url="/redoc",     # ReDoc       → http://localhost:8000/redoc
)


# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",    # Next.js dev server
        "https://wildroute.app",    # production frontend (update when known)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)  # compress large GeoJSON responses


# ── Routers ───────────────────────────────────────────────────────────────────
# Each layer gets its own router and URL prefix.
# Uncomment as each file is created.

app.include_router(ingestion.router, prefix="/ingest",   tags=["L1 — Ingestion"])
# app.include_router(hazard.router,    prefix="/hazard",   tags=["L2 — Hazard Field"])
# app.include_router(scoring.router,   prefix="/score",    tags=["L3 — Risk Scorer"])
# app.include_router(optimizer.router, prefix="/optimize", tags=["L4 — Route Optimizer"])


# ── Health & root ─────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def root():
    return {"message": "WildRoute API — see /docs"}


@app.get("/health", tags=["System"])
def health():
    """
    Lightweight liveness probe.
    Used by Vultr health checks and your frontend to confirm the API is up.
    """
    return {"status": "ok", "version": app.version}


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check API logs."},
    )


# ── Dev entrypoint ────────────────────────────────────────────────────────────
# Run with:  uvicorn main:app --reload --port 8000
# Or directly: python main.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)