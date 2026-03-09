"""
services/snow.py

Fetches snow depth, snowfall, temperature, and rain data for a location
using the Open-Meteo Weather API. No API key required.

Output: HazardPoint with hazard_type="snow" or "black_ice"

Snow/ice risk model:
    - Snow depth on ground + freezing temps = snow hazard
    - Rain or melting + near-freezing temps = black ice hazard  
    - Active snowfall = elevated snow hazard
    - Temperature gradient (above/below 0°C) determines ice risk

Severity mapping:
    low       — light dusting or temps just below 0°C, roads likely treated
    moderate  — measurable snow or patchy ice, reduced traction
    high      — heavy snow or widespread ice, dangerous driving
    critical  — blizzard conditions or sheet ice, avoid travel

Used by: routers/scoring.py, routers/optimizer.py (parallel L1 fetch)
"""

import logging
import httpx
from typing import Optional
from models.schemas import HazardPoint

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


# ─────────────────────────────────────────────────────────────────────────────
# THRESHOLDS
# ─────────────────────────────────────────────────────────────────────────────

# Snow depth thresholds (cm) — what's on the ground right now
SNOW_DEPTH_THRESHOLDS = {
    "light":    1.0,     # dusting — roads may be clear
    "moderate": 5.0,     # measurable — plowed roads still slippery
    "heavy":   15.0,     # significant — reduced visibility + traction
}

# Black ice conditions: rain or melt + temp near/below freezing
BLACK_ICE_TEMP_CEILING = 2.0   # °C — wet roads can freeze below this
BLACK_ICE_TEMP_FLOOR  = -2.0   # °C — below this, surfaces are frozen solid


def _classify_snow_hazard(
    temp_c: float,
    snow_depth_cm: float,
    snowfall_cm: float,
    rain_mm: float,
) -> Optional[tuple[str, str, float]]:
    """
    Classify snow/ice hazard from weather conditions.
    
    Returns:
        (hazard_type, severity, spatial_radius_km) or None if no hazard.
    """
    # ── Black ice detection (most dangerous — check first) ────────────
    # Rain or melting snow + near-freezing = invisible ice on roads
    if temp_c <= BLACK_ICE_TEMP_CEILING and (rain_mm > 0.5 or (snow_depth_cm > 0 and temp_c > -1.0)):
        if temp_c <= BLACK_ICE_TEMP_FLOOR:
            return ("black_ice", "critical", 15.0)
        elif temp_c <= 0.0:
            return ("black_ice", "high", 12.0)
        else:
            return ("black_ice", "moderate", 8.0)

    # ── Active snowfall ───────────────────────────────────────────────
    if snowfall_cm > 0 and temp_c <= 1.0:
        if snowfall_cm >= 5.0:
            return ("snow", "critical", 20.0)
        elif snowfall_cm >= 2.0:
            return ("snow", "high", 15.0)
        elif snowfall_cm >= 0.5:
            return ("snow", "moderate", 10.0)
        else:
            return ("snow", "low", 5.0)

    # ── Snow on ground (no active snowfall) ───────────────────────────
    if snow_depth_cm > 0 and temp_c <= 2.0:
        if snow_depth_cm >= SNOW_DEPTH_THRESHOLDS["heavy"]:
            return ("snow", "high", 15.0)
        elif snow_depth_cm >= SNOW_DEPTH_THRESHOLDS["moderate"]:
            return ("snow", "moderate", 10.0)
        elif snow_depth_cm >= SNOW_DEPTH_THRESHOLDS["light"]:
            return ("snow", "low", 5.0)

    # ── Freezing temps with no precipitation (dry cold) ───────────────
    # Still a hazard — bridges freeze, residual moisture ices over
    if temp_c <= -5.0:
        return ("black_ice", "low", 5.0)

    return None


def _build_url(lat: float, lon: float) -> str:
    return (
        f"{OPEN_METEO_URL}"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,snowfall,snow_depth,rain,weather_code"
        f"&temperature_unit=celsius"
        f"&forecast_days=1"
    )


async def get_snow_hazard(lat: float, lon: float) -> Optional[HazardPoint]:
    """
    Fetch current snow/ice conditions at a location.

    Returns a HazardPoint with hazard_type="snow" or "black_ice",
    or None if conditions are safe.
    """
    url = _build_url(lat, lon)
    logger.info("Fetching snow/ice data: lat=%s lon=%s", lat, lon)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Open-Meteo returned HTTP {e.response.status_code}: {e}")
    except httpx.RequestError as e:
        raise RuntimeError(f"Failed to reach Open-Meteo: {e}")

    try:
        current = data["current"]
        temp_c       = float(current.get("temperature_2m") or 0)
        snowfall_cm  = float(current.get("snowfall") or 0)
        snow_depth_m = float(current.get("snow_depth") or 0)
        rain_mm      = float(current.get("rain") or 0)
        weather_code = int(current.get("weather_code") or 0)
    except (KeyError, TypeError, ValueError) as e:
        raise RuntimeError(f"Unexpected Open-Meteo response: {e}")

    snow_depth_cm = snow_depth_m * 100  # API returns metres

    logger.info(
        "Snow/ice at (%.4f, %.4f): temp=%.1f°C snow_depth=%.1fcm snowfall=%.1fcm rain=%.1fmm wmo=%d",
        lat, lon, temp_c, snow_depth_cm, snowfall_cm, rain_mm, weather_code,
    )

    result = _classify_snow_hazard(temp_c, snow_depth_cm, snowfall_cm, rain_mm)
    if not result:
        logger.info("No snow/ice hazard at (%.4f, %.4f)", lat, lon)
        return None

    hazard_type, severity, radius = result

    return HazardPoint(
        lat=lat,
        lon=lon,
        hazard_type=hazard_type,
        severity=severity,
        source="Open-Meteo Weather",
        confidence=None,
        spatial_impact_radius=radius,
        metadata={
            "temperature_c": temp_c,
            "snow_depth_cm": round(snow_depth_cm, 1),
            "snowfall_cm":   round(snowfall_cm, 1),
            "rain_mm":       round(rain_mm, 1),
            "weather_code":  weather_code,
        },
    )


async def get_snow_hazards_for_route(
    points: list[tuple[float, float]],
    sample_every: int = 3,
) -> list[HazardPoint]:
    """
    Fetch snow/ice hazards along a route.
    Same sampling pattern as AQI and wind services.
    """
    sampled = points[::sample_every]
    logger.info(
        "Fetching snow/ice for %d sampled route points (of %d total)",
        len(sampled), len(points),
    )

    hazards: list[HazardPoint] = []
    for lat, lon in sampled:
        try:
            hazard = await get_snow_hazard(lat, lon)
            if hazard:
                hazards.append(hazard)
        except RuntimeError as e:
            logger.warning("Skipping snow fetch for (%.4f, %.4f): %s", lat, lon, e)

    logger.info("Found %d snow/ice hazard points along route.", len(hazards))
    return hazards


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    async def _test():
        # Test a cold location
        lat, lon = 51.05, -114.07  # Calgary
        print(f"Fetching snow/ice hazard for ({lat}, {lon}) ...")
        hazard = await get_snow_hazard(lat, lon)
        if hazard:
            print(f"  Type: {hazard.hazard_type}")
            print(f"  Severity: {hazard.severity}")
            print(f"  Metadata: {hazard.metadata}")
        else:
            print("  No snow/ice hazard.")

        # Test a warm location
        lat2, lon2 = 28.0, -81.5  # Florida
        print(f"\nFetching snow/ice hazard for ({lat2}, {lon2}) ...")
        hazard2 = await get_snow_hazard(lat2, lon2)
        if hazard2:
            print(f"  Type: {hazard2.hazard_type}")
            print(f"  Severity: {hazard2.severity}")
        else:
            print("  No snow/ice hazard (expected for Florida).")

    asyncio.run(_test())