"""
envcanada.py

Fetches current wind data for a given location using WeatherAPI.com.
Output: WindVector (from models.schemas) — consumed by L2 alongside
        HazardPoint to determine smoke polygon stretch direction and speed.

Env var required: WEATHER_API_KEY
"""

import asyncio
import logging
import time
import httpx
import os
from typing import Optional
from models.schemas import WindVector

logger = logging.getLogger(__name__)

WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
WEATHER_API_URL = "http://api.weatherapi.com/v1/current.json"

if not WEATHER_API_KEY:
    logger.warning("WEATHER_API_KEY not set — wind fetches will fail")

# Cache TTL in seconds — wind shifts gradually
CACHE_TTL_SECONDS = 600  # 10 minutes

# Local in-memory cache: key -> (timestamp, WindVector)
_wind_cache: dict[tuple[float, float], tuple[float, WindVector]] = {}

# Concurrency limit for parallel fetches
_FETCH_SEMAPHORE = asyncio.Semaphore(10)


def _cache_get(key: tuple[float, float]) -> tuple[bool, Optional[WindVector]]:
    """Return (hit, value). Expired entries are evicted."""
    if key in _wind_cache:
        ts, value = _wind_cache[key]
        if time.monotonic() - ts < CACHE_TTL_SECONDS:
            return True, value
        del _wind_cache[key]
    return False, None


def _cache_set(key: tuple[float, float], value: WindVector) -> None:
    _wind_cache[key] = (time.monotonic(), value)


def _fallback_wind(lat: float, lon: float) -> WindVector:
    """Return calm-wind fallback so the L2 pipeline doesn't crash."""
    return WindVector(
        lat=lat, lon=lon,
        station_id="fallback-calm",
        speed_kmh=5.0, direction_deg=0, gusts_kmh=0,
    )


async def get_wind_vector(lat: float, lon: float) -> WindVector:
    """
    Fetch the current wind speed, direction, and gusts for the given coordinates.
    Uses WeatherAPI.com (1M requests/month free tier).
    """
    if not WEATHER_API_KEY:
        logger.error("WEATHER_API_KEY is not set")
        return _fallback_wind(lat, lon)

    # Round to 1 decimal place (~11 km) for caching. Wind fields don't change
    # significantly over small distances, so this saves lots of API calls.
    cache_key = (round(lat, 1), round(lon, 1))
    hit, cached = _cache_get(cache_key)
    if hit and cached is not None:
        logger.debug("Wind cache hit for %s", cache_key)
        return WindVector(
            lat=lat,
            lon=lon,
            station_id=cached.station_id,
            speed_kmh=cached.speed_kmh,
            direction_deg=cached.direction_deg,
            gusts_kmh=cached.gusts_kmh,
        )

    params = {
        "key": WEATHER_API_KEY,
        "q": f"{lat},{lon}",
    }

    try:
        async with _FETCH_SEMAPHORE:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(WEATHER_API_URL, params=params)
                response.raise_for_status()
                data = response.json()

        current = data.get("current")
        if current is None:
            logger.warning("WeatherAPI returned no 'current' block for (%.4f, %.4f)", lat, lon)
            return _fallback_wind(lat, lon)

        # WeatherAPI uses meteorological convention (wind coming FROM direction)
        vec = WindVector(
            lat=lat,
            lon=lon,
            station_id=f"weatherapi-{data['location']['name']}",
            speed_kmh=float(current["wind_kph"]),
            direction_deg=float(current["wind_degree"]),
            gusts_kmh=float(current.get("gust_kph") or 0),
        )

        _cache_set(cache_key, vec)
        logger.info(
            "Wind at (%.4f, %.4f): %.1f km/h from %.0f° (gusts %.1f km/h)",
            lat, lon, vec.speed_kmh, vec.direction_deg, vec.gusts_kmh,
        )
        return vec

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            logger.error("WeatherAPI 403 — check WEATHER_API_KEY is valid")
        elif e.response.status_code == 429:
            logger.error("WeatherAPI rate limit hit — consider increasing cache TTL")
        else:
            logger.error("WeatherAPI HTTP %d for (%.4f, %.4f): %s", e.response.status_code, lat, lon, e)
        return _fallback_wind(lat, lon)

    except Exception as e:
        logger.error("WeatherAPI wind fetch failed for (%.4f, %.4f): %s", lat, lon, e)
        return _fallback_wind(lat, lon)


async def get_wind_vectors_for_route(
    points: list[tuple[float, float]],
    sample_every: int = 10,
) -> list[WindVector]:
    """Fetch wind vectors for sampled points along a route (in parallel)."""
    sampled = points[::sample_every]
    logger.info("Fetching wind for %d sampled route points via WeatherAPI", len(sampled))

    results = await asyncio.gather(
        *(get_wind_vector(lat, lon) for lat, lon in sampled),
        return_exceptions=True,
    )

    vectors: list[WindVector] = []
    for r in results:
        if isinstance(r, WindVector):
            vectors.append(r)
        elif isinstance(r, Exception):
            logger.warning("Wind fetch exception in gather: %s", r)

    return vectors


# ── Local test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def _test():
        # Waterloo, ON
        lat, lon = 43.4643, -80.5204
        logger.info("Testing WeatherAPI Wind Fetch...")
        wind = await get_wind_vector(lat, lon)
        print(f"Result: {wind}")

        # Test cache hit
        wind2 = await get_wind_vector(lat + 0.01, lon + 0.01)
        print(f"Cached: {wind2}")

        # Test route sampling
        route_points = [(lat + i * 0.01, lon + i * 0.01) for i in range(20)]
        vectors = await get_wind_vectors_for_route(route_points, sample_every=2)
        print(f"Fetched {len(vectors)} vectors for route.")

    asyncio.run(_test())