"""
services/wind_interpolation.py

Inverse-distance weighted (IDW) wind interpolation.

Problem: We have wind readings at sampled route points, but fires
aren't on the route. We need wind speed/direction at the fire's
location. This module interpolates from the nearest wind samples.

Used by: services/hazard_field.py → generate_hazard_field()
"""

import math
import logging
from models.schemas import WindVector

logger = logging.getLogger(__name__)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
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


def _weighted_wind_direction(directions: list[float], weights: list[float]) -> float:
    """
    Average wind directions using vector decomposition.

    You can't just average 350° and 10° arithmetically (you'd get 180°, which
    is backwards). Instead, decompose each direction into x/y components,
    do a weighted average, then convert back to degrees.
    """
    wx = sum(w * math.sin(math.radians(d)) for d, w in zip(directions, weights))
    wy = sum(w * math.cos(math.radians(d)) for d, w in zip(directions, weights))
    avg_deg = math.degrees(math.atan2(wx, wy)) % 360
    return round(avg_deg, 2)


def interpolate_wind(
    lat: float,
    lon: float,
    wind_vectors: list[WindVector],
    n_nearest: int = 3,
) -> dict:
    """
    Interpolate wind speed and direction at (lat, lon) from nearby WindVectors.

    Uses inverse-distance weighting: closer stations have more influence.
    If the point lands exactly on a station, that station's values are returned directly.

    Args:
        lat, lon:      Target point (typically a fire's location).
        wind_vectors:  Available wind samples from L1 (sampled along route).
        n_nearest:     How many nearest stations to use (default 3).

    Returns:
        {"speed_kmh": float, "direction_deg": float, "gusts_kmh": float | None}

    Raises:
        ValueError: If wind_vectors is empty.
    """
    if not wind_vectors:
        raise ValueError("No wind vectors available for interpolation.")

    # Calculate distance from target point to every wind station
    with_dist = []
    for wv in wind_vectors:
        dist = _haversine_km(lat, lon, wv.lat, wv.lon)
        with_dist.append((dist, wv))

    # Sort by distance and take the N closest
    with_dist.sort(key=lambda x: x[0])
    nearest = with_dist[:n_nearest]

    # If we're right on top of a station, just return its values
    if nearest[0][0] < 0.1:
        wv = nearest[0][1]
        return {
            "speed_kmh": wv.speed_kmh,
            "direction_deg": wv.direction_deg,
            "gusts_kmh": wv.gusts_kmh,
        }

    # IDW weights: w = 1 / distance²
    weights = [1.0 / (d ** 2) for d, _ in nearest]
    total_weight = sum(weights)
    norm_weights = [w / total_weight for w in weights]

    # Weighted average speed
    avg_speed = sum(w * wv.speed_kmh for w, (_, wv) in zip(norm_weights, nearest))

    # Weighted average direction (vector method — handles wrap-around)
    avg_direction = _weighted_wind_direction(
        [wv.direction_deg for _, wv in nearest],
        norm_weights,
    )

    # Weighted average gusts (skip if any station is missing gust data)
    gusts = [wv.gusts_kmh for _, wv in nearest if wv.gusts_kmh is not None]
    avg_gusts = None
    if len(gusts) == len(nearest):
        gust_weights = norm_weights
        avg_gusts = round(sum(w * g for w, g in zip(gust_weights, gusts)), 2)

    logger.debug(
        "Interpolated wind at (%.4f, %.4f): %.1f km/h from %.1f°",
        lat, lon, avg_speed, avg_direction,
    )

    return {
        "speed_kmh": round(avg_speed, 2),
        "direction_deg": avg_direction,
        "gusts_kmh": avg_gusts,
    }