"""
envcanada.py

Fetches current wind data for a given location using the Open-Meteo API.
No API key required.

Output: WindVector (from models.schemas) — consumed by L2 alongside
        HazardPoint to determine smoke polygon stretch direction and speed.
"""

import logging
import httpx

from models.schemas import WindVector

logger = logging.getLogger(_name_)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _build_url(lat: float, lon: float) -> str:
    return (
        f"{OPEN_METEO_URL}"
        f"?latitude={lat}&longitude={lon}"
        f"&current=wind_speed_10m,wind_direction_10m,wind_gusts_10m"
        f"&wind_speed_unit=kmh"
        f"&forecast_days=1"
    )


async def get_wind_vector(lat: float, lon: float) -> WindVector:
    """
    Fetch the current wind speed, direction, and gusts for the given coordinates.

    Uses Open-Meteo — no API key required.

    Args:
        lat: Latitude of the point of interest (e.g. fire hotspot or route segment).
        lon: Longitude of the point of interest.

    Returns:
        WindVector with speed, direction, and gusts normalised into schemas.WindVector.

    Note on direction convention:
        direction_deg follows meteorological convention — the direction the wind
        is coming FROM (not blowing to). L2 must invert this to get the smoke
        drift vector. e.g. 270° = wind from the west = smoke drifts eastward.

    Raises:
        RuntimeError: If the API call fails or returns unexpected data.
    """
    url = _build_url(lat, lon)
    logger.info("Fetching wind data from Open-Meteo: lat=%s lon=%s", lat, lon)

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
        speed     = float(current["wind_speed_10m"])
        direction = float(current["wind_direction_10m"])
        gusts     = float(current["wind_gusts_10m"]) if current.get("wind_gusts_10m") else None
    except (KeyError, TypeError, ValueError) as e:
        raise RuntimeError(f"Unexpected Open-Meteo response format: {e}")

    logger.info(
        "Wind at (%.4f, %.4f): %.1f km/h from %.1f° | gusts: %s km/h",
        lat, lon, speed, direction, gusts
    )

    return WindVector(
        lat=lat,
        lon=lon,
        station_id=f"open-meteo-{lat:.4f},{lon:.4f}",
        speed_kmh=speed,
        direction_deg=direction,
        gusts_kmh=gusts,
    )


async def get_wind_vectors_for_route(
    points: list[tuple[float, float]],
    sample_every: int = 3,
) -> list[WindVector]:
    """
    Fetch wind vectors for multiple points along a route.

    Rather than querying every single segment point (expensive), samples
    every Nth point. L2 interpolates between samples when building the
    hazard field.

    Args:
        points:       List of (lat, lon) tuples from the decoded route polyline.
        sample_every: Query one point every N points (default 3).

    Returns:
        List of WindVector objects, one per sampled point.
    """
    sampled = points[::sample_every]
    logger.info("Fetching wind for %d sampled route points (of %d total)", len(sampled), len(points))

    vectors: list[WindVector] = []
    for lat, lon in sampled:
        try:
            vec = await get_wind_vector(lat, lon)
            vectors.append(vec)
        except RuntimeError as e:
            logger.warning("Skipping wind fetch for (%.4f, %.4f): %s", lat, lon, e)

    return vectors


# ── Local test ────────────────────────────────────────────────────────────────
if _name_ == "_main_":
    import asyncio

    async def _test():
        # Kamloops, BC — common wildfire zone
        lat, lon = 50.6745, -120.3273
        print(f"Fetching wind vector for ({lat}, {lon}) ...")
        wind = await get_wind_vector(lat, lon)
        print(wind)

        # Test route sampling
        route_points = [(50.6 + i * 0.05, -120.3 + i * 0.02) for i in range(10)]
        print("\nFetching wind for route points...")
        vectors = await get_wind_vectors_for_route(route_points, sample_every=3)
        for v in vectors:
            print(v)

    asyncio.run(_test())
    