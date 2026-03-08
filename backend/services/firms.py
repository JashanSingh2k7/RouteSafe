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

# Query all three satellite sources for maximum coverage
FIRMS_SOURCES = [
    "VIIRS_SNPP_NRT",       
    "VIIRS_NOAA20_NRT",     
    "VIIRS_NOAA21_NRT",    
    "MODIS_NRT",            
]

# Confidence thresholds
# VIIRS: 'l' = low, 'n' = nominal, 'h' = high
# MODIS: integer 0–100, we treat >= 50 as nominal
VIIRS_CONFIDENCE_FILTER = {"l", "n", "h"}
MODIS_CONFIDENCE_MIN = 0


def _build_area_param(lat: float, lon: float, radius_km: float = 50.0) -> str:
    """Convert a centre point + radius into FIRMS bounding-box string (W,S,E,N)."""
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


def _row_to_hazard(row: dict, source: str) -> Optional[HazardPoint]:
    """
    Map a single FIRMS CSV row to a HazardPoint.
    Handles both VIIRS and MODIS confidence formats.
    """
    try:
        confidence = row.get("confidence", "").strip()

        # VIIRS uses string confidence: l/n/h
        # MODIS uses integer confidence: 0–100
        if source.startswith("MODIS"):
            try:
                conf_int = int(confidence)
                if conf_int < MODIS_CONFIDENCE_MIN:
                    return None
                # Normalize to string for metadata
                confidence = "h" if conf_int >= 80 else "n" if conf_int >= 50 else "l"
            except ValueError:
                return None
        else:
            confidence = confidence.lower()
            if confidence not in VIIRS_CONFIDENCE_FILTER:
                return None

        frp = float(row.get("frp", 0) or 0)

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
            source=f"NASA FIRMS ({source})",
            metadata={
                "frp_mw":     frp,
                "confidence": confidence,
                "bright_ti4": row.get("bright_ti4"),
                "acq_date":   row.get("acq_date"),
                "acq_time":   row.get("acq_time"),
                "satellite":  row.get("satellite") or source,
            },
        )
    except (KeyError, ValueError) as e:
        logger.warning("Skipping malformed FIRMS row: %s | error: %s", row, e)
        return None


def _deduplicate_fires(hazards: list[HazardPoint], threshold_km: float = 1.0) -> list[HazardPoint]:
    """
    Remove duplicate detections from overlapping satellites.
    If two fires are within threshold_km of each other, keep the one with higher FRP.
    """
    import math

    def _dist_km(a, b):
        R = 6371.0
        dlat = math.radians(b.lat - a.lat)
        dlon = math.radians(b.lon - a.lon)
        x = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(a.lat))
            * math.cos(math.radians(b.lat))
            * math.sin(dlon / 2) ** 2
        )
        return R * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))

    # Sort by FRP descending so higher-FRP fires survive
    sorted_hazards = sorted(hazards, key=lambda h: h.metadata.get("frp_mw", 0), reverse=True)
    kept = []

    for fire in sorted_hazards:
        is_duplicate = False
        for existing in kept:
            if _dist_km(fire, existing) < threshold_km:
                is_duplicate = True
                break
        if not is_duplicate:
            kept.append(fire)

    return kept


async def get_fire_hazards(
    lat: float,
    lon: float,
    radius_km: float = 50.0,
    day_range: int = 3,
) -> list[HazardPoint]:
    """
    Fetch active fire hotspots near (lat, lon) from all FIRMS satellite sources.

    Queries VIIRS SNPP, VIIRS NOAA-20, and MODIS in parallel,
    merges results, and deduplicates overlapping detections.
    """
    if not FIRMS_MAP_KEY:
        raise ValueError(
            "NASA_FIRMS_API_KEY is not set. "
            "Get a free MAP key at https://firms.modaps.eosdis.nasa.gov/api/map_key/"
        )

    area = _build_area_param(lat, lon, radius_km)
    all_hazards: list[HazardPoint] = []

    async with httpx.AsyncClient(timeout=20.0) as client:
        for source in FIRMS_SOURCES:
            url = f"{FIRMS_BASE_URL}/{FIRMS_MAP_KEY}/{source}/{area}/{day_range}"
            logger.info("Fetching FIRMS data (%s): %s", source, url)

            try:
                response = await client.get(url)

                print(f"\n[DEBUG] --- {source} ---")
                print(f"[DEBUG] URL: {url.replace(FIRMS_MAP_KEY, 'HIDDEN_KEY')}")
                print(f"[DEBUG] Status Code: {response.status_code}")
                print(f"[DEBUG] Raw Text: {response.text[:300]}\n")

                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.warning("FIRMS %s returned HTTP %s — skipping.", source, e.response.status_code)
                continue
            except httpx.RequestError as e:
                logger.warning("FIRMS %s request failed: %s — skipping.", source, e)
                continue

            raw = response.text

            if not raw.strip() or "latitude" not in raw:
                if raw.strip():
                    logger.warning("FIRMS %s failed silently. Raw response: %s", source, raw.strip()[:200])
                else:
                    logger.info("No active fires from %s.", source)
                continue

            rows = _parse_firms_csv(raw)
            logger.info("FIRMS %s returned %d raw hotspot rows.", source, len(rows))

            for row in rows:
                point = _row_to_hazard(row, source)
                if point:
                    all_hazards.append(point)

    # Deduplicate across satellites — same fire seen by multiple sensors
    before_dedup = len(all_hazards)
    all_hazards = _deduplicate_fires(all_hazards)

    logger.info(
        "FIRMS total: %d detections → %d after dedup from %d sources.",
        before_dedup, len(all_hazards), len(FIRMS_SOURCES),
    )

    return all_hazards