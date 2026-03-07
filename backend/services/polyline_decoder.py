"""
services/polyline_decoder.py

Decodes Google Maps encoded polyline strings into lat/lon points,
then builds RouteSegment objects for L3 scoring.

Google Directions API returns routes as encoded polyline strings.
This module is the bridge between that and our internal RouteSegment schema.

Used by: routers/scoring.py
"""

import math
import logging
from models.schemas import RouteSegment

logger = logging.getLogger(__name__)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two points."""
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


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """
    Decode a Google Maps encoded polyline into (lat, lon) pairs.

    Algorithm: each character encodes 5 bits of a varint.
    Subtract 63, check continuation bit (0x20), accumulate,
    then apply sign and divide by 1e5 for precision.
    """
    points = []
    index = 0
    lat = 0
    lng = 0

    while index < len(encoded):
        # Decode latitude delta
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lat += (~(result >> 1) if (result & 1) else (result >> 1))

        # Decode longitude delta
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lng += (~(result >> 1) if (result & 1) else (result >> 1))

        points.append((lat / 1e5, lng / 1e5))

    return points


def build_segments(
    points: list[tuple[float, float]],
    total_duration_min: float,
) -> list[RouteSegment]:
    """
    Convert decoded polyline points into RouteSegment objects.

    Travel time per segment is distributed proportionally by distance.
    This is more accurate than assuming uniform speed — highway segments
    get more time per km than city segments (roughly).

    Args:
        points:             List of (lat, lon) from decode_polyline().
        total_duration_min: Total trip duration in minutes (from Google Directions).

    Returns:
        List of RouteSegment objects ready for L3 scoring.
    """
    if len(points) < 2:
        logger.warning("Need at least 2 points to build segments, got %d", len(points))
        return []

    # Calculate distance for each segment
    distances = []
    for i in range(len(points) - 1):
        d = _haversine_km(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
        distances.append(d)

    total_distance = sum(distances)
    if total_distance == 0:
        logger.warning("Total route distance is 0 — all points identical?")
        return []

    # Distribute trip duration proportionally by segment distance
    segments = []
    cumulative_time = 0.0

    for i, dist in enumerate(distances):
        # Skip zero-length segments (duplicate points in polyline)
        if dist < 0.001:
            continue

        travel_time = (dist / total_distance) * total_duration_min
        segments.append(RouteSegment(
            index=len(segments),
            start_lat=points[i][0],
            start_lon=points[i][1],
            end_lat=points[i + 1][0],
            end_lon=points[i + 1][1],
            distance_km=round(dist, 4),
            travel_time_min=round(travel_time, 3),
            cumulative_time_min=round(cumulative_time, 3),
        ))
        cumulative_time += travel_time

    logger.info(
        "Built %d segments — total %.1f km, %.1f min",
        len(segments), total_distance, total_duration_min,
    )
    return segments


def compute_route_center(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Average lat/lon of all points — used as center for FIRMS query."""
    avg_lat = sum(p[0] for p in points) / len(points)
    avg_lon = sum(p[1] for p in points) / len(points)
    return round(avg_lat, 6), round(avg_lon, 6)


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Short encoded polyline: Calgary → Banff (approximate)
    test_encoded = "_{~xHxdajTfAnBrCxGdBzH?lFsBpHoFpGwG`FaHtCaGx@"

    points = decode_polyline(test_encoded)
    print(f"Decoded {len(points)} points")
    for p in points[:5]:
        print(f"  ({p[0]:.5f}, {p[1]:.5f})")

    segments = build_segments(points, total_duration_min=90.0)
    print(f"\nBuilt {len(segments)} segments")
    for seg in segments[:5]:
        print(f"  #{seg.index}: {seg.distance_km:.2f} km, "
              f"{seg.travel_time_min:.1f} min, cumulative={seg.cumulative_time_min:.1f} min")

    center = compute_route_center(points)
    print(f"\nRoute center: ({center[0]}, {center[1]})")
    