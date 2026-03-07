"""
routers/ingestion.py

L1 — Data Ingestion endpoints.
Exposes NASA FIRMS, wind, and AQI services as HTTP endpoints.
L2 calls /ingest/all to get everything it needs in one parallel request.
"""

import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services import firms, envcanada, aqi
from models.schemas import HazardPoint, WindVector
from typing import Optional


logger = logging.getLogger(__name__)

router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class RoutePoints(BaseModel):
    """Request body for /ingest/all — the decoded route polyline as lat/lon pairs."""
    points:     list[tuple[float, float]]  # [(lat, lon), ...]
    center_lat: float                      # midpoint of route — used for FIRMS query
    center_lon: float
    radius_km:  float = 100.0             # how far from the route to check for fires


class IngestAllResponse(BaseModel):
    """Combined L1 response — everything L2 needs to build the hazard field."""
    fire_hazards:  list[HazardPoint]
    wind_vectors:  list[WindVector]
    aqi_hazards:   list[HazardPoint]
    total_hazards: int


# ── GET /ingest/fires ─────────────────────────────────────────────────────────

@router.get(
    "/fires",
    response_model=list[HazardPoint],
    summary="Fetch active fire hotspots near a location",
    description=(
        "Queries NASA FIRMS VIIRS satellite data for active fire hotspots "
        "within a given radius. Returns only nominal and high confidence detections."
    ),
)
async def get_fires(
    lat:       float = Query(...,  description="Centre latitude",             example=51.0),
    lon:       float = Query(...,  description="Centre longitude",            example=-115.5),
    radius_km: float = Query(50.0, description="Search radius in kilometres", example=50.0),
    day_range: int   = Query(1,    description="How many days back to query", ge=1, le=10),
):
    logger.info("GET /ingest/fires — lat=%s lon=%s radius=%skm", lat, lon, radius_km)
    try:
        hazards = await firms.get_fire_hazards(
            lat=lat, lon=lon, radius_km=radius_km, day_range=day_range,
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("FIRMS fetch failed: %s", e)
        raise HTTPException(status_code=502, detail=f"FIRMS API error: {e}")
    return hazards


# ── GET /ingest/wind ──────────────────────────────────────────────────────────

@router.get(
    "/wind",
    response_model=WindVector,
    summary="Fetch current wind vector at a location",
    description=(
        "Fetches wind speed, direction, and gusts from Open-Meteo "
        "at the given coordinates. Used by L2 to determine smoke drift direction."
    ),
)
async def get_wind(
    lat: float = Query(..., description="Latitude",  example=51.0),
    lon: float = Query(..., description="Longitude", example=-115.5),
):
    logger.info("GET /ingest/wind — lat=%s lon=%s", lat, lon)
    try:
        vector = await envcanada.get_wind_vector(lat=lat, lon=lon)
    except RuntimeError as e:
        logger.exception("Wind fetch failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Wind API error: {e}")
    return vector


# ── GET /ingest/aqi ───────────────────────────────────────────────────────────

@router.get(
    "/aqi",
    response_model=Optional[HazardPoint],
    summary="Fetch AQI smoke hazard at a location",
    description=(
        "Fetches PM2.5 and AQI from Open-Meteo Air Quality API. "
        "Returns a HazardPoint with hazard_type='smoke' if air quality is poor, "
        "or null if air is clean."
    ),
)
async def get_aqi(
    lat: float = Query(..., description="Latitude",  example=51.0),
    lon: float = Query(..., description="Longitude", example=-115.5),
):
    logger.info("GET /ingest/aqi — lat=%s lon=%s", lat, lon)
    try:
        hazard = await aqi.get_aqi_hazard(lat=lat, lon=lon)
    except RuntimeError as e:
        logger.exception("AQI fetch failed: %s", e)
        raise HTTPException(status_code=502, detail=f"AQI API error: {e}")
    return hazard


# ── POST /ingest/all ──────────────────────────────────────────────────────────

@router.post(
    "/all",
    response_model=IngestAllResponse,
    summary="Fetch all hazard data for a route in parallel",
    description=(
        "The primary L1 endpoint. Calls FIRMS, wind, and AQI services "
        "simultaneously using asyncio.gather(). Returns everything L2 needs "
        "to build the hazard field in a single request."
    ),
)
async def ingest_all(body: RoutePoints):
    """
    Runs all three ingestion services in parallel and returns combined results.
    This is what L2 calls — not the individual endpoints above.

    - Fire hotspots queried around the route centre point
    - Wind vectors sampled along the route polyline
    - AQI hazards sampled along the route polyline

    All three run concurrently via asyncio.gather() to minimise latency.
    """
    logger.info(
        "POST /ingest/all — %d route points, centre=(%.4f, %.4f), radius=%skm",
        len(body.points), body.center_lat, body.center_lon, body.radius_km,
    )

    try:
        fire_hazards, wind_vectors, aqi_hazards = await asyncio.gather(
            firms.get_fire_hazards(
                lat=body.center_lat,
                lon=body.center_lon,
                radius_km=body.radius_km,
            ),
            envcanada.get_wind_vectors_for_route(
                points=body.points,
                sample_every=3,
            ),
            aqi.get_aqi_hazards_for_route(
                points=body.points,
                sample_every=3,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Parallel ingestion failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Ingestion error: {e}")

    total = len(fire_hazards) + len(aqi_hazards)
    logger.info(
        "Ingestion complete — %d fires, %d wind vectors, %d AQI hazards",
        len(fire_hazards), len(wind_vectors), len(aqi_hazards),
    )

    return IngestAllResponse(
        fire_hazards=fire_hazards,
        wind_vectors=wind_vectors,
        aqi_hazards=aqi_hazards,
        total_hazards=total,
    )