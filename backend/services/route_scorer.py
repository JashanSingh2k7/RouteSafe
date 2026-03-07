"""
services/route_scorer.py

L3 — Risk Scorer

Takes RouteSegments + L2's time-bucketed hex grids and scores each segment.

The key idea: a segment 3 hours into the trip should be scored against
the T+2h or T+4h hazard grid (not T+0), because smoke moves over time.
This is what makes our scoring predictive, not just reactive.

Pipeline:
    RouteSegments + grids_by_time
        → for each segment:
            1. Find which H3 hexes the segment passes through
            2. Match segment's arrival time to the nearest time bucket
            3. Look up each hex's severity in that time bucket
            4. Take the worst severity as the segment's risk_score
        → return list[ScoredSegment] + route summary

Consumed by: routers/scoring.py, L4 optimizer
"""

import math
import logging
from typing import Optional

import h3

from models.schemas import RouteSegment, ScoredSegment
from services.hazard_field import H3_RESOLUTION, TIME_HORIZONS_HOURS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Sample a point along the segment every ~1 km to check for hazards.
# Too sparse = miss hazard zones between start/end.
# Too dense = slow for no benefit (H3 res 7 hexes are ~5 km anyway).
SAMPLE_INTERVAL_KM = 1.0

# Risk level thresholds for route-level classification
RISK_THRESHOLDS = {
    "safe":      0.15,    # below this = green
    "moderate":  0.40,    # 0.15–0.40 = yellow
    "dangerous": 0.70,    # 0.40–0.70 = orange
                          # above 0.70 = red (critical)
}

# AQI estimation from severity (rough mapping for frontend display)
# These are approximate PM2.5-based AQI values
SEVERITY_TO_AQI = [
    (0.0,  25),    # clean air
    (0.15, 50),    # good
    (0.30, 100),   # moderate
    (0.45, 150),   # unhealthy for sensitive groups
    (0.60, 200),   # unhealthy
    (0.80, 300),   # very unhealthy
    (1.0,  500),   # hazardous
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
    """
    Find all H3 hexes a segment passes through by sampling points along it.

    Linear interpolation between start/end, sampling every ~1 km.
    Minimum 3 samples (start, mid, end) even for short segments.
    """
    dist = _haversine_km(start_lat, start_lon, end_lat, end_lon)
    n_samples = max(3, int(dist / SAMPLE_INTERVAL_KM) + 1)

    hexes = set()
    for i in range(n_samples):
        t = i / (n_samples - 1)  # 0.0 → 1.0
        lat = start_lat + t * (end_lat - start_lat)
        lon = start_lon + t * (end_lon - start_lon)
        hexes.add(h3.latlng_to_cell(lat, lon, resolution))

    return hexes


def _match_time_bucket(
    cumulative_min: float,
    horizons: list[float] = TIME_HORIZONS_HOURS,
) -> float:
    """
    Snap a segment's arrival time to the nearest available time bucket.

    If equidistant between two buckets, picks the LATER one (conservative —
    smoke has had more time to spread).

    If the segment is beyond the last horizon (e.g. 8 hours into a trip
    but max horizon is 6h), uses the last bucket. Smoke beyond 6h is
    uncertain anyway.
    """
    cumulative_hours = cumulative_min / 60.0

    # Beyond our prediction window — use the last bucket
    if cumulative_hours >= horizons[-1]:
        return horizons[-1]

    # Find the closest bucket, preferring later on ties
    best = horizons[0]
    best_diff = abs(cumulative_hours - horizons[0])

    for h in horizons[1:]:
        diff = abs(cumulative_hours - h)
        if diff <= best_diff:  # <= means ties go to the later bucket
            best = h
            best_diff = diff

    return best


def _estimate_aqi(severity: float) -> float:
    """
    Rough AQI estimate from severity score.
    Uses linear interpolation between the defined breakpoints.
    """
    if severity <= 0.0:
        return SEVERITY_TO_AQI[0][1]

    for i in range(1, len(SEVERITY_TO_AQI)):
        s_prev, aqi_prev = SEVERITY_TO_AQI[i - 1]
        s_curr, aqi_curr = SEVERITY_TO_AQI[i]

        if severity <= s_curr:
            # Interpolate between breakpoints
            ratio = (severity - s_prev) / (s_curr - s_prev) if s_curr != s_prev else 0
            return round(aqi_prev + ratio * (aqi_curr - aqi_prev), 1)

    return SEVERITY_TO_AQI[-1][1]


def _classify_route_risk(max_score: float) -> str:
    """Classify overall route risk level from the worst segment score."""
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
    Score one segment against a hex grid (from the matched time bucket).

    Finds all hexes the segment passes through, looks up their severity,
    and takes the WORST one as the risk score. This is conservative —
    if any part of the segment is dangerous, the whole segment is flagged.
    """
    hexes = _get_segment_hexes(
        segment.start_lat, segment.start_lon,
        segment.end_lat, segment.end_lon,
    )

    # Look up severity for each hex
    max_severity = 0.0
    for hex_id in hexes:
        sev = hex_grid.get(hex_id, 0.0)
        if sev > max_severity:
            max_severity = sev

    # Determine hazard type and AQI estimate
    hazard_type = "smoke" if max_severity > 0.0 else None
    aqi = _estimate_aqi(max_severity) if max_severity > 0.0 else None

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
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def score_route(
    segments: list[RouteSegment],
    grids_by_time: dict[float, dict[str, float]],
) -> dict:
    """
    Score all segments of a route against the time-bucketed hazard field.

    Each segment is matched to the time bucket closest to its arrival time,
    then scored against that bucket's hex grid. This makes scoring PREDICTIVE:
    "when you arrive at this stretch of highway in 3 hours, how bad will
    the smoke be?"

    Args:
        segments:       List of RouteSegment objects from polyline_decoder.
        grids_by_time:  {hours_ahead: {h3_index: severity}} from L2.

    Returns:
        Dict with:
            scored_segments:  list[ScoredSegment] — one per input segment
            max_risk_score:   float — worst segment score on the route
            high_risk_count:  int — segments with risk > 0.40
            route_risk_level: str — "safe" | "moderate" | "dangerous" | "critical"
            total_distance_km: float
            total_time_min:    float
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
        }

    available_horizons = sorted(grids_by_time.keys()) if grids_by_time else [0]

    scored: list[ScoredSegment] = []

    for segment in segments:
        # Match this segment's arrival time to the right hazard snapshot
        bucket = _match_time_bucket(segment.cumulative_time_min, available_horizons)
        hex_grid = grids_by_time.get(bucket, {})

        scored_seg = _score_segment(segment, hex_grid)
        scored.append(scored_seg)

    # Route-level summary stats
    max_risk = max(s.risk_score for s in scored)
    high_risk_count = sum(1 for s in scored if s.risk_score >= RISK_THRESHOLDS["moderate"])
    total_dist = sum(s.distance_km for s in scored)
    total_time = scored[-1].cumulative_time_min + scored[-1].travel_time_min if scored else 0.0

    logger.info(
        "Route scored — %d segments, max_risk=%.3f, high_risk=%d, level=%s",
        len(scored), max_risk, high_risk_count, _classify_route_risk(max_risk),
    )

    return {
        "scored_segments": scored,
        "max_risk_score": round(max_risk, 4),
        "high_risk_count": high_risk_count,
        "route_risk_level": _classify_route_risk(max_risk),
        "total_distance_km": round(total_dist, 2),
        "total_time_min": round(total_time, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from services.hazard_field import generate_hazard_field
    from models.schemas import HazardPoint, WindVector

    # ── Mock L1 data ──────────────────────────────────────────────────────
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

    # ── Run L2 to get hazard field ────────────────────────────────────────
    polygons, flat_grid, grids_by_time = generate_hazard_field(mock_fires, mock_wind, mock_aqi)

    # ── Mock route segments (simulating a ~200km drive past the fire) ─────
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

    # ── Run L3 scoring ────────────────────────────────────────────────────
    result = score_route(mock_segments, grids_by_time)

    print(f"\nRoute risk level: {result['route_risk_level']}")
    print(f"Max risk score:   {result['max_risk_score']}")
    print(f"High-risk segs:   {result['high_risk_count']}/{len(mock_segments)}")
    print(f"Total distance:   {result['total_distance_km']} km")
    print(f"Total time:       {result['total_time_min']} min")

    print("\nPer-segment scores:")
    for seg in result["scored_segments"]:
        bar = "█" * int(seg.risk_score * 20)
        risk_str = f"{seg.risk_score:.3f}"
        aqi_str = f"AQI≈{seg.aqi_estimate:.0f}" if seg.aqi_estimate else "clean"
        print(f"  #{seg.index:02d} [{risk_str}] {bar:<20s} {aqi_str}")
        