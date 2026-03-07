"""
services/route_scorer.py

L3 — Risk Scorer + Smoke Dose Calculator

Scores each route segment against the time-bucketed hazard field,
then calculates cumulative smoke dose for the entire trip.

Two outputs:
    1. Per-segment risk scores (for coloring the route on the map)
    2. Trip-level smoke dose report (the headline cigarette-equivalents metric)

Pipeline:
    RouteSegments + grids_by_time + health_profile
        → score each segment against correct time bucket
        → calculate PM2.5 dose per segment
        → sum into cumulative trip dose
        → convert to cigarette equivalents

Consumed by: routers/scoring.py, L4 optimizer
"""

import math
import logging
from typing import Optional

import h3

from models.schemas import RouteSegment, ScoredSegment
from services.hazard_field import H3_RESOLUTION, TIME_HORIZONS_HOURS
from services.smoke_dose import calculate_trip_dose, severity_to_pm25, TripDose

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_INTERVAL_KM = 1.0

RISK_THRESHOLDS = {
    "safe":      0.15,
    "moderate":  0.40,
    "dangerous": 0.70,
}

SEVERITY_TO_AQI = [
    (0.0,  25),
    (0.15, 50),
    (0.30, 100),
    (0.45, 150),
    (0.60, 200),
    (0.80, 300),
    (1.0,  500),
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_segment_hexes(
    start_lat: float, start_lon: float,
    end_lat: float, end_lon: float,
    resolution: int = H3_RESOLUTION,
) -> set[str]:
    """Find all H3 hexes a segment passes through by sampling every ~1 km."""
    dist = _haversine_km(start_lat, start_lon, end_lat, end_lon)
    n_samples = max(3, int(dist / SAMPLE_INTERVAL_KM) + 1)

    hexes = set()
    for i in range(n_samples):
        t = i / (n_samples - 1)
        lat = start_lat + t * (end_lat - start_lat)
        lon = start_lon + t * (end_lon - start_lon)
        hexes.add(h3.latlng_to_cell(lat, lon, resolution))

    return hexes


def _match_time_bucket(
    cumulative_min: float,
    horizons: list[float] = TIME_HORIZONS_HOURS,
) -> float:
    """Snap a segment's arrival time to the nearest available time bucket.
    Ties go to the later bucket (conservative — smoke has spread more)."""
    cumulative_hours = cumulative_min / 60.0

    if cumulative_hours >= horizons[-1]:
        return horizons[-1]

    best = horizons[0]
    best_diff = abs(cumulative_hours - horizons[0])

    for h in horizons[1:]:
        diff = abs(cumulative_hours - h)
        if diff <= best_diff:
            best = h
            best_diff = diff

    return best


def _estimate_aqi(severity: float) -> float:
    """Severity score → approximate AQI via interpolation."""
    if severity <= 0.0:
        return SEVERITY_TO_AQI[0][1]

    for i in range(1, len(SEVERITY_TO_AQI)):
        s_prev, aqi_prev = SEVERITY_TO_AQI[i - 1]
        s_curr, aqi_curr = SEVERITY_TO_AQI[i]
        if severity <= s_curr:
            ratio = (severity - s_prev) / (s_curr - s_prev) if s_curr != s_prev else 0
            return round(aqi_prev + ratio * (aqi_curr - aqi_prev), 1)

    return SEVERITY_TO_AQI[-1][1]


def _classify_route_risk(max_score: float) -> str:
    """Classify overall route risk from the worst segment score."""
    if max_score < RISK_THRESHOLDS["safe"]:
        return "safe"
    elif max_score < RISK_THRESHOLDS["moderate"]:
        return "moderate"
    elif max_score < RISK_THRESHOLDS["dangerous"]:
        return "dangerous"
    else:
        return "critical"


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE SEGMENT SCORER
# ─────────────────────────────────────────────────────────────────────────────

def _score_segment(
    segment: RouteSegment,
    hex_grid: dict[str, float],
) -> ScoredSegment:
    """
    Score one segment. Finds all hexes it passes through, takes the worst
    severity, and converts to risk score + AQI + PM2.5 estimates.
    """
    hexes = _get_segment_hexes(
        segment.start_lat, segment.start_lon,
        segment.end_lat, segment.end_lon,
    )

    max_severity = 0.0
    for hex_id in hexes:
        sev = hex_grid.get(hex_id, 0.0)
        if sev > max_severity:
            max_severity = sev

    hazard_type = "smoke" if max_severity > 0.0 else None
    aqi = _estimate_aqi(max_severity) if max_severity > 0.0 else None
    pm25 = severity_to_pm25(max_severity) if max_severity > 0.0 else None

    return ScoredSegment(
        index=segment.index,
        start_lat=segment.start_lat,
        start_lon=segment.start_lon,
        end_lat=segment.end_lat,
        end_lon=segment.end_lon,
        distance_km=segment.distance_km,
        travel_time_min=segment.travel_time_min,
        cumulative_time_min=segment.cumulative_time_min,
        risk_score=round(max_severity, 4),
        hazard_type=hazard_type,
        aqi_estimate=aqi,
        pm25_estimate=round(pm25, 2) if pm25 else None,
        smoke_dose_ug=None,  # filled in after dose calculation
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def score_route(
    segments: list[RouteSegment],
    grids_by_time: dict[float, dict[str, float]],
    health_profile: str = "default",
) -> dict:
    """
    Score all segments + calculate cumulative smoke dose.

    Args:
        segments:       RouteSegment objects from polyline_decoder.
        grids_by_time:  {hours_ahead: {h3_index: severity}} from L2.
        health_profile: Key for health profile ("default", "child", "asthma", etc.)

    Returns:
        Dict with scored_segments, route summary stats, and smoke_dose report.
    """
    if not segments:
        logger.warning("No segments to score.")
        return {
            "scored_segments": [],
            "max_risk_score": 0.0,
            "high_risk_count": 0,
            "route_risk_level": "safe",
            "total_distance_km": 0.0,
            "total_time_min": 0.0,
            "smoke_dose": None,
        }

    available_horizons = sorted(grids_by_time.keys()) if grids_by_time else [0]

    scored: list[ScoredSegment] = []

    for segment in segments:
        bucket = _match_time_bucket(segment.cumulative_time_min, available_horizons)
        hex_grid = grids_by_time.get(bucket, {})
        scored_seg = _score_segment(segment, hex_grid)
        scored.append(scored_seg)

    # ── Calculate smoke dose ──────────────────────────────────────────────
    # Build the input list: (segment_index, risk_score, travel_time_min)
    dose_input = [
        (seg.index, seg.risk_score, seg.travel_time_min)
        for seg in scored
    ]
    trip_dose = calculate_trip_dose(dose_input, profile_key=health_profile)

    # Write per-segment dose back onto the ScoredSegment objects
    dose_by_index = {d.segment_index: d for d in trip_dose.segment_doses}
    for seg in scored:
        seg_dose = dose_by_index.get(seg.index)
        if seg_dose:
            seg.smoke_dose_ug = seg_dose.effective_dose_ug

    # ── Route-level summary ───────────────────────────────────────────────
    max_risk = max(s.risk_score for s in scored)
    high_risk_count = sum(1 for s in scored if s.risk_score >= RISK_THRESHOLDS["moderate"])
    total_dist = sum(s.distance_km for s in scored)
    total_time = scored[-1].cumulative_time_min + scored[-1].travel_time_min if scored else 0.0

    logger.info(
        "Route scored — %d segs, max_risk=%.3f, level=%s, dose=%.2f cigarettes [%s]",
        len(scored), max_risk, _classify_route_risk(max_risk),
        trip_dose.cigarette_equivalents, health_profile,
    )

    return {
        "scored_segments": scored,
        "max_risk_score": round(max_risk, 4),
        "high_risk_count": high_risk_count,
        "route_risk_level": _classify_route_risk(max_risk),
        "total_distance_km": round(total_dist, 2),
        "total_time_min": round(total_time, 2),
        "smoke_dose": trip_dose,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from services.hazard_field import generate_hazard_field
    from models.schemas import HazardPoint, WindVector

    mock_fires = [
        HazardPoint(
            lat=51.12, lon=-115.80,
            hazard_type="wildfire", severity="high", source="NASA FIRMS",
            metadata={"frp_mw": 420.0, "confidence": "h"},
        ),
    ]
    mock_wind = [
        WindVector(lat=51.17, lon=-115.57, station_id="s1", speed_kmh=28.0, direction_deg=270.0, gusts_kmh=42.0),
        WindVector(lat=51.08, lon=-115.35, station_id="s2", speed_kmh=24.0, direction_deg=265.0, gusts_kmh=38.0),
        WindVector(lat=51.25, lon=-115.80, station_id="s3", speed_kmh=31.0, direction_deg=275.0, gusts_kmh=45.0),
    ]
    mock_aqi = [
        HazardPoint(
            lat=51.20, lon=-115.60,
            hazard_type="smoke", severity="moderate", source="Open-Meteo AQ",
            spatial_impact_radius=15.0,
            metadata={"pm2_5_ugm3": 42.0, "us_aqi": 112},
        ),
    ]

    polygons, flat_grid, grids_by_time = generate_hazard_field(mock_fires, mock_wind, mock_aqi)

    # Mock route: 20 segments, 10 km each, 6 min each = 200 km, 2 hours
    mock_segments = []
    for i in range(20):
        start_lat = 51.05 + i * 0.02
        start_lon = -116.20 + i * 0.04
        end_lat = 51.05 + (i + 1) * 0.02
        end_lon = -116.20 + (i + 1) * 0.04
        mock_segments.append(RouteSegment(
            index=i,
            start_lat=start_lat, start_lon=start_lon,
            end_lat=end_lat, end_lon=end_lon,
            distance_km=10.0,
            travel_time_min=6.0,
            cumulative_time_min=i * 6.0,
        ))

    # Test with multiple health profiles
    for profile in ["default", "child", "asthma"]:
        result = score_route(mock_segments, grids_by_time, health_profile=profile)
        dose = result["smoke_dose"]

        print(f"\n{'=' * 60}")
        print(f"PROFILE: {dose.profile_label}")
        print(f"{'=' * 60}")
        print(f"Route risk:       {result['route_risk_level']}")
        print(f"Max risk score:   {result['max_risk_score']}")
        print(f"Cigarettes:       {dose.cigarette_equivalents:.2f}")
        print(f"Total dose:       {dose.total_effective_dose_ug:.1f} µg")
        print(f"Peak PM2.5:       {dose.peak_pm25_ugm3:.1f} µg/m³")
        print(f"Avg PM2.5:        {dose.avg_pm25_ugm3:.1f} µg/m³")
        print(f"Time in smoke:    {dose.time_in_smoke_min:.0f} min")
        print(f"Advisory:         {dose.health_advisory[:100]}...")

        print("\nPer-segment:")
        for seg in result["scored_segments"]:
            bar = "█" * int(seg.risk_score * 20)
            dose_str = f"{seg.smoke_dose_ug:.1f}µg" if seg.smoke_dose_ug else "0"
            pm_str = f"PM2.5={seg.pm25_estimate:.0f}" if seg.pm25_estimate else "clean"
            print(f"  #{seg.index:02d} [{seg.risk_score:.3f}] {bar:<20s} {pm_str:<15s} dose={dose_str}")