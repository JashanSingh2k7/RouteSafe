import os
import csv
import io
import logging
from typing import Optional
import httpx
from models.schemas import HazardPoint

logger = logging.getLogger(__name__)

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_MAP_KEY = os.getenv("NASA_FIRMS_API_KEY")

# VIIRS (375m resolution, near-real-time) — best for routing hazards
FIRMS_SOURCE = "VIIRS_SNPP_NRT"

# Confidence thresholds for VIIRS: 'l' = low, 'n' = nominal, 'h' = high
CONFIDENCE_FILTER = {"n", "h"}


def _build_area_param(lat: float, lon: float, radius_km: float = 50.0) -> str:
    """Convert a centre point + radius into FIRMS bounding-box string (W,S,E,N)."""
    # Rough degree conversion (1° ≈ 111 km)
    delta = radius_km / 111.0
    west  = round(lon - delta, 4)
    south = round(lat - delta, 4)
    east  = round(lon + delta, 4)
    north = round(lat + delta, 4)
    return f"{west},{south},{east},{north}"


def _parse_firms_csv(raw_csv: str) -> list[dict]:
    """Parse NASA FIRMS CSV response into a list of row dicts."""
    reader = csv.DictReader(io.StringIO(raw_csv))
    return list(reader)


def _row_to_hazard(row: dict) -> Optional[HazardPoint]:
    """
    Map a single FIRMS CSV row to a HazardPoint.

    Key VIIRS columns:
        latitude, longitude, bright_ti4, bright_ti5,
        frp (fire radiative power, MW), confidence, acq_date, acq_time
    """
    try:
        confidence = row.get("confidence", "").strip().lower()
        if confidence not in CONFIDENCE_FILTER:
            return None

        frp = float(row.get("frp", 0) or 0)

        # Severity: low <10 MW, moderate 10-50 MW, high >50 MW
        if frp >= 50:
            severity = "high"
        elif frp >= 10:
            severity = "moderate"
        else:
            severity = "low"

        return HazardPoint(
            lat=float(row["latitude"]),
            lon=float(row["longitude"]),
            hazard_type="wildfire",
            severity=severity,
            source="NASA FIRMS",
            metadata={
                "frp_mw":     frp,
                "confidence": confidence,
                "bright_ti4": row.get("bright_ti4"),
                "acq_date":   row.get("acq_date"),
                "acq_time":   row.get("acq_time"),
                "satellite":  row.get("satellite"),
            },
        )
    except (KeyError, ValueError) as e:
        logger.warning("Skipping malformed FIRMS row: %s | error: %s", row, e)
        return None


async def get_fire_hazards(
    lat: float,
    lon: float,
    radius_km: float = 50.0,
    day_range: int = 1,
) -> list[HazardPoint]:
    """
    Fetch active fire hotspots near (lat, lon) from the NASA FIRMS API.

    Args:
        lat:        Centre latitude.
        lon:        Centre longitude.
        radius_km:  Search radius in kilometres (default 50 km).
        day_range:  How many days back to query (1–10, default 1).

    Returns:
        List of HazardPoint objects filtered to nominal/high confidence fires.
it
    Raises:
        ValueError:  If the API key is not set.
        httpx.HTTPStatusError: On non-2xx API responses.
    """
    if not FIRMS_MAP_KEY:
        raise ValueError(
            "NASA_FIRMS_API_KEY is not set. "
            "Get a free MAP key at https://firms.modaps.eosdis.nasa.gov/api/map_key/"
        )

    area = _build_area_param(lat, lon, radius_km)
    url = f"{FIRMS_BASE_URL}/{FIRMS_MAP_KEY}/{FIRMS_SOURCE}/{area}/{day_range}"

    logger.info("Fetching FIRMS data: %s", url)

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url)
        response.raise_for_status()

    raw = response.text

    # FIRMS returns a plain-text message (not CSV) when there are no fires
    if not raw.strip() or "latitude" not in raw:
        logger.info("No active fires found in area.")
        return []

    rows = _parse_firms_csv(raw)
    logger.info("FIRMS returned %d raw hotspot rows.", len(rows))

    hazards: list[HazardPoint] = []
    for row in rows:
        point = _row_to_hazard(row)
        if point:
            hazards.append(point)

    logger.info("Parsed %d qualifying fire hazards.", len(hazards))
    return hazards