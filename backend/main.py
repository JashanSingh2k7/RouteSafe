# to run: uvicorn main:app --reload --port 8000

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from dotenv import load_dotenv
load_dotenv()  # MUST be before router imports so env vars are available

from routers import ingestion, scoring, directions

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wildroute")


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("WildRoute API starting up...")
    yield
    logger.info("WildRoute API shutting down...")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="WildRoute API",
    description=(
        "Wildfire-aware routing engine. "
        "Ingests NASA FIRMS, Environment Canada, and AQI data, "
        "generates smoke-dispersion hazard fields, and scores / optimises routes."
    ),
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:3000",
    "http://localhost:5173",
    "https://wildroute.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(ingestion.router, prefix="/ingest", tags=["L1 — Ingestion"])
app.include_router(scoring.router,   prefix="/score",  tags=["L3 — Risk Scorer"])
app.include_router(directions.router, prefix="/directions", tags=["Directions"])
# app.include_router(hazard.router,    prefix="/hazard",   tags=["L2 — Hazard Field"])
# app.include_router(optimizer.router, prefix="/optimize", tags=["L4 — Route Optimizer"])


# ── Health & root ─────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def root():
    return {"message": "WildRoute API — see /docs"}


@app.get("/health", tags=["System"])
def health():
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
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)