"""
routers/optimizer.py

L4 — Route Optimizer endpoint.

POST /optimize/route — runs the full L1→L2→L3→L4 pipeline:
    decode polyline → fetch hazard data → build hazard field →
    score route → generate avoidance waypoints

The frontend flow:
    1. User enters origin/destination → clicks "Score Route"
    2. Frontend calls POST /score/route → sees risk level
    3. If dangerous, user clicks "Optimize Route"
    4. Frontend calls POST /optimize/route
    5. If rerouted=true, frontend re-queries Google Directions
       with the returned waypoints and re-scores the new route
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.schemas import HazardPoint, HazardPolygon, ScoredSegment, SmokeDoseReport, OptimizedRoute
from services import firms, envcanada, aqi
from services.polyline_decoder import decode_polyline, build_segments, compute_route_center
from services.hazard_field import generate_hazard_field
from services.route_scorer import score_route
from services.optimizer import optimize_route
from services.smoke_dose import PROFILES

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST / RESPONSE
# ─────────────────────────────────────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    """What the frontend sends to get an optimized route."""
    encoded_polyline:   str   = Field(..., description="Google Directions encoded polyline string")
    total_duration_min: float = Field(..., description="Total trip duration in minutes")
    origin:             str   = Field(..., description="Origin location string")
    destination:        str   = Field(..., description="Destination location string")
    radius_km:          float = Field(100.0, description="Fire search radius (km)")
    day_range:          int   = Field(1, description="FIRMS lookback days", ge=1, le=10)
    wind_sample_every:  int   = Field(5, description="Sample wind every N polyline points")
    aqi_sample_every:   int   = Field(5, description="Sample AQI every N polyline points")
    health_profile:     str   = Field("default", description="Health profile key")
    risk_threshold:     float = Field(0.40, description="Risk score that triggers avoidance", ge=0.1, le=1.0)


class OptimizeResponse(BaseModel):
    """Full pipeline output including avoidance waypoints."""
    # Scored route + hazard data (same as ScoreRouteResponse)
    scored_segments:    list[ScoredSegment]
    hazard_polygons:    list[HazardPolygon]
    fire_hazards:       list[HazardPoint]
    hex_grid:           dict[str, float]
    smoke_dose:         SmokeDoseReport
    max_risk_score:     float
    high_risk_count:    int
    route_risk_level:   str

    # Optimization output
    waypoints:          list[dict]        # [{lat, lon}, ...] for Google Directions
    rerouted:           bool
    clusters_found:     int
    clusters_resolved:  int
    avoidance_details:  list[dict]
    remaining_max_risk: float

    # Route totals
    total_distance_km:  float
    total_time_min:     float
    fire_count:         int
    hex_count:          int
    briefing:           str


# ─────────────────────────────────────────────────────────────────────────────
# POST /optimize/route
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/route",
    response_model=OptimizeResponse,
    summary="Score and optimize a route against wildfire hazards",
    description=(
        "Full L1→L2→L3→L4 pipeline. Returns scored segments, hazard polygons, "
        "fire locations, hex grid, smoke dose report, AND avoidance waypoints "
        "if any segment exceeds the risk threshold."
    ),
)
async def optimize_route_endpoint(body: OptimizeRequest):

    # ── 1. Decode polyline ────────────────────────────────────────────────
    try:
        points = decode_polyline(body.encoded_polyline)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Polyline decode failed: {e}")

    if len(points) < 2:
        raise HTTPException(status_code=400, detail="Polyline must have ≥ 2 points.")

    segments = build_segments(points, body.total_duration_min)
    if not segments:
        raise HTTPException(status_code=400, detail="Could not build segments from polyline.")

    center_lat, center_lon = compute_route_center(points)

    logger.info(
        "POST /optimize/route — %d pts, %d segs, center=(%.4f, %.4f), profile=%s, threshold=%.2f",
        len(points), len(segments), center_lat, center_lon,
        body.health_profile, body.risk_threshold,
    )

    # ── 2. L1: Parallel data fetch ───────────────────────────────────────
    try:
        fire_hazards, wind_vectors, aqi_hazards = await asyncio.gather(
            firms.get_fire_hazards(
                lat=center_lat, lon=center_lon,
                radius_km=body.radius_km, day_range=body.day_range,
            ),
            envcanada.get_wind_vectors_for_route(
                points=points, sample_every=body.wind_sample_every,
            ),
            aqi.get_aqi_hazards_for_route(
                points=points, sample_every=body.aqi_sample_every,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("L1 ingestion failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Data ingestion error: {e}")

    # ── 3. L2: Hazard field ──────────────────────────────────────────────
    try:
        polygons, flat_grid, grids_by_time = generate_hazard_field(
            fires=fire_hazards, wind_vectors=wind_vectors, aqi_hazards=aqi_hazards,
        )
    except Exception as e:
        logger.exception("L2 failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Hazard field error: {e}")

    # ── 4. L3: Score route ───────────────────────────────────────────────
    try:
        score_result = score_route(segments, grids_by_time, health_profile=body.health_profile)
    except Exception as e:
        logger.exception("L3 failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Scoring error: {e}")

    # ── 5. L4: Optimize ─────────────────────────────────────────────────
    try:
        opt_result = optimize_route(
            scored_segments=score_result["scored_segments"],
            grids_by_time=grids_by_time,
            flat_grid=flat_grid,
            health_profile=body.health_profile,
            threshold=body.risk_threshold,
        )
    except Exception as e:
        logger.exception("L4 failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Optimization error: {e}")

    # ── 6. Build dose report ─────────────────────────────────────────────
    trip_dose = score_result["smoke_dose"]
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

    # ── 7. Build briefing ────────────────────────────────────────────────
    if opt_result["rerouted"]:
        briefing = (
            f"Found {opt_result['clusters_found']} high-risk zone(s). "
            f"Generated {len(opt_result['waypoints'])} avoidance waypoint(s). "
        )
        for d in opt_result["avoidance_details"]:
            briefing += (
                f"Segments {d['cluster_start']}–{d['cluster_end']}: "
                f"detour {d['detour_km']:.1f} km "
                f"(severity {d['original_severity_sum']:.1f} → {d['new_severity_sum']:.1f}). "
            )
    else:
        briefing = "Route is within acceptable risk levels. No rerouting needed."

    # ── 8. Response ──────────────────────────────────────────────────────
    return OptimizeResponse(
        scored_segments=score_result["scored_segments"],
        hazard_polygons=polygons,
        fire_hazards=fire_hazards,
        hex_grid=flat_grid,
        smoke_dose=dose_report,
        max_risk_score=score_result["max_risk_score"],
        high_risk_count=score_result["high_risk_count"],
        route_risk_level=score_result["route_risk_level"],
        waypoints=opt_result["waypoints"],
        rerouted=opt_result["rerouted"],
        clusters_found=opt_result["clusters_found"],
        clusters_resolved=opt_result["clusters_resolved"],
        avoidance_details=opt_result["avoidance_details"],
        remaining_max_risk=opt_result["remaining_max_risk"],
        total_distance_km=score_result["total_distance_km"],
        total_time_min=score_result["total_time_min"],
        fire_count=len(fire_hazards),
        hex_count=len(flat_grid),
        briefing=briefing,
    )