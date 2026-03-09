"""
aqi.py

Fetches current air quality index (AQI) and PM2.5 data for a given location
using the WAQI (AQICN) API. 
Generous free tier: 1000 requests per minute.

Output: HazardPoint with hazard_type="smoke" — consumed by L2 alongside
        fire HazardPoints and WindVectors to build the full hazard field.
"""

import asyncio
import logging
import time
import httpx
import os
from models.schemas import HazardPoint
from typing import Optional

logger = logging.getLogger(__name__)

# Fallback token for dev; ideally set this in your .env file
WAQI_TOKEN = os.getenv("WAQI_TOKEN", "demo")
WAQI_BASE_URL = "https://api.waqi.info/feed"

# ---------------------------------------------------------------------------
# NOTE: WAQI's iaqi.pm25.v returns an AQI *sub-index*, NOT raw µg/m³.
# These thresholds use the EPA AQI scale directly:
#   0-50   = Good
#   51-100 = Moderate
#   101-150 = Unhealthy for Sensitive Groups
#   151-200 = Unhealthy
#   201+   = Very Unhealthy / Hazardous
# ---------------------------------------------------------------------------
AQI_THRESHOLDS = {
    "low":      50,
    "moderate": 100,
    "high":     150,
}

# Cache TTL in seconds (AQI data refreshed ~hourly by most stations)
CACHE_TTL_SECONDS = 900  # 15 minutes

# Local in-memory cache: key -> (timestamp, value)
_aqi_cache: dict[tuple[float, float], tuple[float, Optional[HazardPoint]]] = {}

# Concurrency limit for parallel fetches (stay well under 1000 rpm)
_FETCH_SEMAPHORE = asyncio.Semaphore(20)


def _aqi_to_severity(aqi: float) -> str:
    if aqi <= AQI_THRESHOLDS["low"]:
        return "low"
    elif aqi <= AQI_THRESHOLDS["moderate"]:
        return "moderate"
    elif aqi <= AQI_THRESHOLDS["high"]:
        return "high"
    else:
        return "critical"


def _aqi_to_radius_km(aqi: float) -> float:
    """Spatial impact radius in km — larger AQI implies broader regional haze."""
    if aqi <= AQI_THRESHOLDS["low"]:
        return 5.0
    elif aqi <= AQI_THRESHOLDS["moderate"]:
        return 15.0
    elif aqi <= AQI_THRESHOLDS["high"]:
        return 30.0
    else:
        return 50.0


def _cache_get(key: tuple[float, float]) -> tuple[bool, Optional[HazardPoint]]:
    """Return (hit, value). Expired entries are evicted."""
    if key in _aqi_cache:
        ts, value = _aqi_cache[key]
        if time.monotonic() - ts < CACHE_TTL_SECONDS:
            return True, value
        del _aqi_cache[key]
    return False, None


def _cache_set(key: tuple[float, float], value: Optional[HazardPoint]) -> None:
    _aqi_cache[key] = (time.monotonic(), value)


async def get_aqi_hazard(lat: float, lon: float) -> Optional[HazardPoint]:
    """
    Fetch current AQI from the nearest station via WAQI API.
    Returns a HazardPoint only when air quality exceeds the "low" threshold.
    """
    # Round to 2 decimal places (~1.1 km) to group nearby route samples
    cache_key = (round(lat, 2), round(lon, 2))
    hit, cached = _cache_get(cache_key)
    if hit:
        logger.debug("AQI cache hit for %s", cache_key)
        return cached

    url = f"{WAQI_BASE_URL}/geo:{lat};{lon}/?token={WAQI_TOKEN}"

    try:
        async with _FETCH_SEMAPHORE:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

        if data.get("status") != "ok":
            logger.warning("WAQI API error for (%s, %s): %s", lat, lon, data.get("data"))
            return None

        station_data = data["data"]

        # iaqi.pm25.v is the AQI sub-index for PM2.5 (NOT raw µg/m³).
        # Fall back to composite AQI if PM2.5 sub-index is unavailable.
        pm25_aqi = station_data.get("iaqi", {}).get("pm25", {}).get("v")
        composite_aqi = station_data.get("aqi", 0)
        aqi_value = float(pm25_aqi if pm25_aqi is not None else composite_aqi)

        if aqi_value <= AQI_THRESHOLDS["low"]:
            _cache_set(cache_key, None)
            return None

        # "dominentpol" is intentionally misspelled — that's the actual WAQI key
        hazard = HazardPoint(
            lat=lat,
            lon=lon,
            hazard_type="smoke",
            severity=_aqi_to_severity(aqi_value),
            source=f"WAQI: {station_data.get('city', {}).get('name', 'Unknown Station')}",
            confidence=None,
            spatial_impact_radius=_aqi_to_radius_km(aqi_value),
            metadata={
                "pm25_aqi_index": aqi_value,
                "composite_aqi": composite_aqi,
                "station_id": station_data.get("idx"),
                "dominant_pollutant": station_data.get("dominentpol"),
            },
        )

        _cache_set(cache_key, hazard)
        return hazard

    except Exception as e:
        logger.error("WAQI fetch failed for (%.4f, %.4f): %s", lat, lon, e)
        return None


async def get_aqi_hazards_for_route(
    points: list[tuple[float, float]],
    sample_every: int = 5,
) -> list[HazardPoint]:
    """Sample AQI along a route and return detected hazards (fetched in parallel)."""
    sampled = points[::sample_every]
    logger.info("Fetching WAQI for %d sampled route points", len(sampled))

    results = await asyncio.gather(
        *(get_aqi_hazard(lat, lon) for lat, lon in sampled),
        return_exceptions=True,
    )

    hazards: list[HazardPoint] = []
    for r in results:
        if isinstance(r, HazardPoint):
            hazards.append(r)
        elif isinstance(r, Exception):
            logger.warning("AQI fetch exception in gather: %s", r)

    return hazards


if __name__ == "__main__":
    async def _test():
        logging.basicConfig(level=logging.DEBUG)
        # Kamloops, BC
        lat, lon = 50.6745, -120.3273
        logger.info("Testing WAQI Fetch...")
        hazard = await get_aqi_hazard(lat, lon)
        if hazard:
            print(f"Hazard Found: {hazard.severity} severity at {hazard.source}")
            print(f"  PM2.5 AQI sub-index: {hazard.metadata['pm25_aqi_index']}")
        else:
            print("Air quality good or station unavailable.")

    asyncio.run(_test())