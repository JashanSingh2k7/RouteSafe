"""
routers/scoring.py

L3 — Risk Scoring + Smoke Dose endpoints.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.schemas import HazardPoint, HazardPolygon, ScoredSegment, SmokeDoseReport
from services import firms, envcanada, aqi
from services.polyline_decoder import decode_polyline, build_segments, compute_route_center
from services.hazard_field import generate_hazard_field
from services.route_scorer import score_route
from services.smoke_dose import PROFILES

logger = logging.getLogger(__name__)
router = APIRouter()


class ScoreRouteRequest(BaseModel):
    encoded_polyline:   str   = Field(..., description="Google Directions encoded polyline string")
    total_duration_min: float = Field(..., description="Total trip duration in minutes")
    radius_km:          float = Field(100.0)
    day_range:          int   = Field(1, ge=1, le=10)
    wind_sample_every:  int   = Field(5)
    aqi_sample_every:   int   = Field(5)
    health_profile:     str   = Field("default")


class ScoreRouteResponse(BaseModel):
    scored_segments:    list[ScoredSegment]
    hazard_polygons:    list[HazardPolygon]
    fire_hazards:       list[HazardPoint]
    hex_grid:           dict[str, float]
    smoke_dose:         SmokeDoseReport
    max_risk_score:     float
    high_risk_count:    int
    route_risk_level:   str
    total_distance_km:  float
    total_time_min:     float
    fire_count:         int
    hex_count:          int


class ProfileInfo(BaseModel):
    key:             str
    label:           str
    breathing_rate:  float
    sensitivity:     float


@router.get("/profiles", response_model=list[ProfileInfo], summary="List available health profiles")
async def get_profiles():
    return [
        ProfileInfo(key=key, label=p.label, breathing_rate=p.breathing_rate_m3h, sensitivity=p.sensitivity)
        for key, p in PROFILES.items()
    ]


@router.post("/route", response_model=ScoreRouteResponse, summary="Score a route against wildfire and smoke hazards")
async def score_route_endpoint(body: ScoreRouteRequest):

    try:
        points = decode_polyline(body.encoded_polyline)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode polyline: {e}")

    if len(points) < 2:
        raise HTTPException(status_code=400, detail="Polyline must contain at least 2 points.")

    segments = build_segments(points, body.total_duration_min)
    if not segments:
        raise HTTPException(status_code=400, detail="Could not build route segments.")

    center_lat, center_lon = compute_route_center(points)

    logger.info("POST /score/route — %d points, %d segments, profile=%s",
                len(points), len(segments), body.health_profile)

    try:
        fire_hazards, wind_vectors, aqi_hazards = await asyncio.gather(
            firms.get_fire_hazards(lat=center_lat, lon=center_lon,
                                   radius_km=body.radius_km, day_range=body.day_range),
            envcanada.get_wind_vectors_for_route(points=points, sample_every=body.wind_sample_every),
            aqi.get_aqi_hazards_for_route(points=points, sample_every=body.aqi_sample_every),
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("L1 ingestion failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Data ingestion error: {e}")

    try:
        polygons, flat_grid, grids_by_time = generate_hazard_field(
            fires=fire_hazards, wind_vectors=wind_vectors, aqi_hazards=aqi_hazards,
        )
    except Exception as e:
        logger.exception("L2 failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Hazard field error: {e}")

    try:
        result = score_route(segments, grids_by_time, health_profile=body.health_profile)
    except Exception as e:
        logger.exception("L3 failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Scoring error: {e}")

    trip_dose = result["smoke_dose"]
    dose_report = SmokeDoseReport(
        total_dose_ug=trip_dose.total_effective_dose_ug,
        cigarette_equivalents=trip_dose.cigarette_equivalents,
        profile_used=trip_dose.profile_used,
        profile_label=trip_dose.profile_label,
        peak_pm25_ugm3=trip_dose.peak_pm25_ugm3,
        avg_pm25_ugm3=trip_dose.avg_pm25_ugm3,
        time_in_smoke_min=trip_dose.time_in_smoke_min,
        health_advisory=trip_dose.health_advisory,
    )

    return ScoreRouteResponse(
        scored_segments=result["scored_segments"],
        hazard_polygons=polygons,
        fire_hazards=fire_hazards,
        hex_grid=flat_grid,
        smoke_dose=dose_report,
        max_risk_score=result["max_risk_score"],
        high_risk_count=result["high_risk_count"],
        route_risk_level=result["route_risk_level"],
        total_distance_km=result["total_distance_km"],
        total_time_min=result["total_time_min"],
        fire_count=len(fire_hazards),
        hex_count=len(flat_grid),
    )