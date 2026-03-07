"""
routers/scoring.py

L3 — Risk Scoring endpoint.

POST /score/route is the main endpoint the frontend calls.
It orchestrates the full pipeline:
    1. Decode the polyline into route segments
    2. Call L1 to fetch fire, wind, AQI data along the route
    3. Call L2 to build the hazard field
    4. Call L3 to score each segment
    5. Return scored segments + route summary + hazard polygons

The frontend uses this to paint the route red/yellow/green on the map
and display hazard polygons as overlay zones.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.schemas import HazardPolygon, ScoredSegment
from services import firms, envcanada, aqi
from services.polyline_decoder import decode_polyline, build_segments, compute_route_center
from services.hazard_field import generate_hazard_field
from services.route_scorer import score_route

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST / RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────────────────

class ScoreRouteRequest(BaseModel):
    """What the frontend sends to score a route."""
    encoded_polyline:  str              = Field(..., description="Google Directions encoded polyline string")
    total_duration_min: float           = Field(..., description="Total trip duration in minutes (from Directions API)")
    radius_km:          float           = Field(100.0, description="How far from route to search for fires (km)")
    day_range:          int             = Field(1, description="FIRMS lookback days (1–10)", ge=1, le=10)
    wind_sample_every:  int             = Field(5, description="Sample wind every N polyline points")
    aqi_sample_every:   int             = Field(5, description="Sample AQI every N polyline points")


class ScoreRouteResponse(BaseModel):
    """Full pipeline output — scored route + hazard field for the map."""
    scored_segments:   list[ScoredSegment]
    hazard_polygons:   list[HazardPolygon]
    max_risk_score:    float
    high_risk_count:   int
    route_risk_level:  str                          # "safe" | "moderate" | "dangerous" | "critical"
    total_distance_km: float
    total_time_min:    float
    fire_count:        int                          # how many active fires were found
    hex_count:         int                          # how many H3 hexes in the hazard field


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/route",
    response_model=ScoreRouteResponse,
    summary="Score a route against wildfire and smoke hazards",
    description=(
        "The primary endpoint for the frontend. Accepts an encoded polyline, "
        "runs the full L1→L2→L3 pipeline, and returns risk scores per segment "
        "plus hazard polygons for map visualization."
    ),
)
async def score_route_endpoint(body: ScoreRouteRequest):
    """
    Full pipeline: decode polyline → fetch hazards → build field → score segments.
    """

    # ── 1. Decode polyline ────────────────────────────────────────────────
    try:
        points = decode_polyline(body.encoded_polyline)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode polyline: {e}")

    if len(points) < 2:
        raise HTTPException(status_code=400, detail="Polyline must contain at least 2 points.")

    segments = build_segments(points, body.total_duration_min)
    if not segments:
        raise HTTPException(status_code=400, detail="Could not build route segments from polyline.")

    center_lat, center_lon = compute_route_center(points)

    logger.info(
        "POST /score/route — %d points, %d segments, center=(%.4f, %.4f)",
        len(points), len(segments), center_lat, center_lon,
    )

    # ── 2. L1: Fetch fire, wind, AQI data in parallel ────────────────────
    try:
        fire_hazards, wind_vectors, aqi_hazards = await asyncio.gather(
            firms.get_fire_hazards(
                lat=center_lat,
                lon=center_lon,
                radius_km=body.radius_km,
                day_range=body.day_range,
            ),
            envcanada.get_wind_vectors_for_route(
                points=points,
                sample_every=body.wind_sample_every,
            ),
            aqi.get_aqi_hazards_for_route(
                points=points,
                sample_every=body.aqi_sample_every,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("L1 ingestion failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Data ingestion error: {e}")

    logger.info(
        "L1 complete — %d fires, %d wind vectors, %d AQI hazards",
        len(fire_hazards), len(wind_vectors), len(aqi_hazards),
    )

    # ── 3. L2: Build hazard field ─────────────────────────────────────────
    try:
        polygons, flat_grid, grids_by_time = generate_hazard_field(
            fires=fire_hazards,
            wind_vectors=wind_vectors,
            aqi_hazards=aqi_hazards,
        )
    except Exception as e:
        logger.exception("L2 hazard field generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Hazard field error: {e}")

    # ── 4. L3: Score route segments ───────────────────────────────────────
    try:
        result = score_route(segments, grids_by_time)
    except Exception as e:
        logger.exception("L3 scoring failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Route scoring error: {e}")

    # ── 5. Return combined response ───────────────────────────────────────
    return ScoreRouteResponse(
        scored_segments=result["scored_segments"],
        hazard_polygons=polygons,
        max_risk_score=result["max_risk_score"],
        high_risk_count=result["high_risk_count"],
        route_risk_level=result["route_risk_level"],
        total_distance_km=result["total_distance_km"],
        total_time_min=result["total_time_min"],
        fire_count=len(fire_hazards),
        hex_count=len(flat_grid),
    )