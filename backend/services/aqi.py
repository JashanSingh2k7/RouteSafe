"""
aqi.py

Fetches current air quality index (AQI) and PM2.5 data for a given location
using the Open-Meteo Air Quality API.
No API key required.

Output: HazardPoint with hazard_type="smoke" — consumed by L2 alongside
        fire HazardPoints and WindVectors to build the full hazard field.

Why AQI matters for routing:
    A route segment can be dangerous from smoke even if there's no active fire
    nearby — smoke travels. AQI stations give us ground-truth smoke presence
    that satellite fire detection alone can miss (e.g. smoke from a fire 200km
    away drifting over a highway).
"""

import logging
import httpx

from models.schemas import HazardPoint
from typing import Optional

logger = logging.getLogger(__name__)

OPEN_METEO_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# PM2.5 thresholds (µg/m³) — based on Canada's AQHI breakpoints
# These map to HazardPoint severity levels
PM25_THRESHOLDS = {
    "low":      12.0,   # 0–12   µg/m³ — good air quality
    "moderate": 35.4,   # 12–35  µg/m³ — moderate, sensitive groups affected
    "high":     55.4,   # 35–55  µg/m³ — unhealthy for all
                        # >55    µg/m³ — critical, route should be avoided
}


def _pm25_to_severity(pm25: float) -> str:
    """Map a PM2.5 reading to a severity string for HazardPoint."""
    if pm25 <= PM25_THRESHOLDS["low"]:
        return "low"
    elif pm25 <= PM25_THRESHOLDS["moderate"]:
        return "moderate"
    elif pm25 <= PM25_THRESHOLDS["high"]:
        return "high"
    else:
        return "critical"


def _pm25_to_radius(pm25: float) -> float:
    """
    Estimate spatial impact radius (km) from PM2.5 concentration.
    Higher concentration = larger area affected around that point.
    L2 uses this as the base radius before applying wind stretch.
    """
    if pm25 <= PM25_THRESHOLDS["low"]:
        return 5.0
    elif pm25 <= PM25_THRESHOLDS["moderate"]:
        return 15.0
    elif pm25 <= PM25_THRESHOLDS["high"]:
        return 30.0
    else:
        return 50.0


def _build_url(lat: float, lon: float) -> str:
    return (
        f"{OPEN_METEO_AQ_URL}"
        f"?latitude={lat}&longitude={lon}"
        f"&current=pm2_5,us_aqi,dust"
        f"&forecast_days=1"
    )


async def get_aqi_hazard(lat: float, lon: float) -> Optional[HazardPoint]:
    """
    Fetch current AQI and PM2.5 for a location and return a HazardPoint.

    Returns None if air quality is good (below low threshold) — no hazard
    to add to the field.

    Args:
        lat: Latitude of the point to check.
        lon: Longitude of the point to check.

    Returns:
        HazardPoint with hazard_type="smoke", or None if air is clean.

    Raises:
        RuntimeError: If the API call fails or returns unexpected data.
    """
    url = _build_url(lat, lon)
    logger.info("Fetching AQI data: lat=%s lon=%s", lat, lon)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Open-Meteo AQ API returned HTTP {e.response.status_code}: {e}")
    except httpx.RequestError as e:
        raise RuntimeError(f"Failed to reach Open-Meteo AQ API: {e}")

    try:
        current = data["current"]
        pm25    = float(current.get("pm2_5") or 0)
        us_aqi  = float(current.get("us_aqi") or 0)
        dust    = float(current.get("dust")   or 0)
    except (KeyError, TypeError, ValueError) as e:
        raise RuntimeError(f"Unexpected Open-Meteo AQ response format: {e}")

    logger.info(
        "AQI at (%.4f, %.4f): PM2.5=%.1f µg/m³ | US AQI=%.0f | dust=%.1f",
        lat, lon, pm25, us_aqi, dust
    )

    # Don't create a hazard point for clean air — keeps the hazard field lean
    if pm25 <= PM25_THRESHOLDS["low"]:
        logger.info("Air quality good at (%.4f, %.4f) — no hazard created.", lat, lon)
        return None

    severity = _pm25_to_severity(pm25)
    radius   = _pm25_to_radius(pm25)

    return HazardPoint(
        lat=lat,
        lon=lon,
        hazard_type="smoke",
        severity=severity,
        source="Open-Meteo AQ",
        confidence=None,            # AQI is measured, not probabilistic
        spatial_impact_radius=radius,
        metadata={
            "pm2_5_ugm3": pm25,
            "us_aqi":     us_aqi,
            "dust_ugm3":  dust,
        },
    )


async def get_aqi_hazards_for_route(
    points: list[tuple[float, float]],
    sample_every: int = 3,
) -> list[HazardPoint]:
    """
    Fetch AQI hazard points for multiple locations along a route.

    Samples every Nth point to keep API calls reasonable — same pattern
    as get_wind_vectors_for_route() in envcanada.py.

    Args:
        points:       List of (lat, lon) tuples from the decoded route polyline.
        sample_every: Query one point every N points (default 3).

    Returns:
        List of HazardPoint objects where smoke was detected.
        Clean-air points are excluded (get_aqi_hazard returns None for those).
    """
    sampled = points[::sample_every]
    logger.info(
        "Fetching AQI for %d sampled route points (of %d total)",
        len(sampled), len(points)
    )

    hazards: list[HazardPoint] = []
    for lat, lon in sampled:
        try:
            hazard = await get_aqi_hazard(lat, lon)
            if hazard:
                hazards.append(hazard)
        except RuntimeError as e:
            logger.warning("Skipping AQI fetch for (%.4f, %.4f): %s", lat, lon, e)

    logger.info("Found %d smoke hazard points along route.", len(hazards))
    return hazards


# ── Local test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    async def _test():
        # Kamloops, BC — frequently affected by wildfire smoke
        lat, lon = 50.6745, -120.3273
        print(f"Fetching AQI hazard for ({lat}, {lon}) ...")
        hazard = await get_aqi_hazard(lat, lon)
        if hazard:
            print(hazard)
        else:
            print("Air quality good — no hazard point created.")

        # Test route sampling
        route_points = [(50.6 + i * 0.05, -120.3 + i * 0.02) for i in range(10)]
        print("\nFetching AQI for route points...")
        hazards = await get_aqi_hazards_for_route(route_points, sample_every=3)
        for h in hazards:
            print(h)

    asyncio.run(_test())