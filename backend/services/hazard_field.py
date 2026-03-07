"""
services/hazard_field.py

L2 — Hazard Field Generator

Takes L1 data (fire hotspots, wind vectors, AQI readings) and produces:
  1. HazardPolygons — time-stamped smoke zones for frontend map visualization
  2. H3 hex grid    — fast-lookup danger scores for L3 route scoring

Pipeline:
    L1 fires + wind + AQI
        → interpolate wind at each fire
        → generate smoke plume ellipses per fire per time step
        → rasterise plumes onto H3 hex grid with severity decay
        → merge overlapping plumes + overlay AQI ground-truth
        → output HazardPolygons + hex grid dict

Consumed by: routers/hazard.py, L3 risk scorer
"""

import math
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field

import h3

from models.schemas import HazardPoint, HazardPolygon, WindVector
from services.wind_interpolation import interpolate_wind

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL DATA STRUCTURES (never leave L2)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SmokePlume:
    """One fire's projected smoke zone at a specific future time."""
    fire_lat:           float
    fire_lon:           float
    valid_at:           datetime
    hours_ahead:        float
    severity_base:      float                       # 0.0–1.0 from FRP
    coordinates:        list[list[float]]           # [[lon, lat], ...] GeoJSON ring
    wind_speed_kmh:     float
    wind_direction_deg: float


@dataclass
class HazardCell:
    """One H3 hexagon with a danger score. L3 does O(1) lookups on these."""
    h3_index:    str
    severity:    float                              # 0.0–1.0
    hazard_type: str
    valid_at:    datetime
    sources:     list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION — tweak these during testing / demo prep
# ─────────────────────────────────────────────────────────────────────────────

TIME_HORIZONS_HOURS: list[float] = [0, 1, 2, 4, 6]

# H3 resolution 7 ≈ 5.16 km² per hex
H3_RESOLUTION: int = 7

MAX_SEVERITY: float = 1.0
MIN_SEVERITY_THRESHOLD: float = 0.05

# Base smoke radius (km) before wind stretching
BASE_RADIUS_KM = {
    "low":      10.0,
    "moderate": 25.0,
    "high":     50.0,
    "critical": 80.0,
}

# FRP normalization ceiling (a ~500 MW fire = severity 1.0)
FRP_SEVERITY_MAX = 500.0

# Severity decay constants
TIME_DECAY_RATE = 0.15          # smoke dilutes over time: severity × e^(-rate × hours)
DISTANCE_DECAY_RATE = 0.04      # smoke weakens with distance from fire centre


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _frp_to_severity(fire: HazardPoint) -> float:
    """Convert FRP (fire radiative power, MW) to 0.0–1.0 severity.
    Falls back to severity string if FRP metadata is missing."""
    frp = fire.metadata.get("frp_mw")
    if frp is not None:
        return min(float(frp) / FRP_SEVERITY_MAX, 1.0)
    mapping = {"low": 0.2, "moderate": 0.5, "high": 0.8, "critical": 1.0}
    return mapping.get(fire.severity, 0.5)


def _offset_point(lat: float, lon: float, dx_km: float, dy_km: float) -> tuple[float, float]:
    """Offset a lat/lon by dx_km east and dy_km north. Flat-earth approx, fine within ~200 km."""
    new_lat = lat + (dy_km / 111.0)
    new_lon = lon + (dx_km / (111.0 * math.cos(math.radians(lat))))
    return new_lat, new_lon


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
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


# ─────────────────────────────────────────────────────────────────────────────
# PLUME GENERATION — one fire, one time step → one polygon
# ─────────────────────────────────────────────────────────────────────────────

def _generate_plume(
    fire: HazardPoint,
    wind: dict,
    hours_ahead: float,
    now: datetime,
    severity_base: float,
) -> SmokePlume:
    """
    Build a wind-stretched ellipse for one fire at one time horizon.

    Shape logic:
        - Downwind radius = base + drift distance (wind pushes smoke forward)
        - Upwind radius   = base (smoke doesn't travel against wind)
        - Crosswind radius = base × 0.4 + small drift spread
    The ellipse is rotated to align with the wind travel direction.
    """
    speed = wind["speed_kmh"]
    direction = wind["direction_deg"]
    drift_km = speed * hours_ahead

    base_radius = BASE_RADIUS_KM.get(fire.severity, 25.0)

    downwind_radius  = base_radius + drift_km
    upwind_radius    = base_radius
    crosswind_radius = base_radius * 0.4 + (drift_km * 0.1)

    # Wind comes FROM direction_deg, smoke travels TO the opposite
    travel_deg = (direction + 180) % 360
    travel_rad = math.radians(travel_deg)

    # Shift plume centre downwind from fire
    drift_dx = math.sin(travel_rad) * drift_km * 0.5
    drift_dy = math.cos(travel_rad) * drift_km * 0.5
    centre_lat, centre_lon = _offset_point(fire.lat, fire.lon, drift_dx, drift_dy)

    # Build ellipse as 36 points (every 10°), rotated to wind direction
    coords = []
    for angle_deg in range(0, 360, 10):
        angle_rad = math.radians(angle_deg)

        # Local ellipse coordinates (x = east, y = north)
        local_x = crosswind_radius * math.sin(angle_rad)
        local_y = (
            downwind_radius if math.cos(angle_rad) >= 0 else upwind_radius
        ) * math.cos(angle_rad)

        # Rotate to align with wind travel direction
        rotated_x = local_x * math.cos(travel_rad) - local_y * math.sin(travel_rad)
        rotated_y = local_x * math.sin(travel_rad) + local_y * math.cos(travel_rad)

        pt_lat, pt_lon = _offset_point(centre_lat, centre_lon, rotated_x, rotated_y)
        coords.append([pt_lon, pt_lat])  # GeoJSON order

    # Close the ring
    coords.append(coords[0])

    return SmokePlume(
        fire_lat=fire.lat,
        fire_lon=fire.lon,
        valid_at=now + timedelta(hours=hours_ahead),
        hours_ahead=hours_ahead,
        severity_base=severity_base,
        coordinates=coords,
        wind_speed_kmh=speed,
        wind_direction_deg=direction,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SEVERITY DECAY — smoke weakens over time and distance
# ─────────────────────────────────────────────────────────────────────────────

def _decay_severity(base_severity: float, hours_ahead: float, distance_km: float = 0.0) -> float:
    """
    Compute severity at a specific hex, accounting for both:
      - Time decay:     smoke dilutes as it disperses over hours
      - Distance decay: hexes far from fire centre are less dangerous

    Returns 0.0–1.0 severity score.
    """
    time_factor = math.exp(-TIME_DECAY_RATE * hours_ahead)
    distance_factor = math.exp(-DISTANCE_DECAY_RATE * distance_km)
    return base_severity * time_factor * distance_factor


# ─────────────────────────────────────────────────────────────────────────────
# H3 RASTERISATION — plume polygon → set of hex cells with severity
# ─────────────────────────────────────────────────────────────────────────────

def _rasterise_plume(plume: SmokePlume, resolution: int = H3_RESOLUTION) -> list[HazardCell]:
    """
    Convert a SmokePlume polygon into H3 hex cells.

    Uses h3 v4 API: polygon_to_cells() to find all hexes inside the plume,
    then assigns each hex a severity score decayed by time AND distance
    from the fire source.
    """
    # Time-only severity check — skip if the plume is too weak at this time step
    time_decayed = _decay_severity(plume.severity_base, plume.hours_ahead, distance_km=0.0)
    if time_decayed < MIN_SEVERITY_THRESHOLD:
        return []

    # h3 v4: polygon_to_cells expects an H3Poly object
    # Convert our [[lon, lat], ...] ring to [(lat, lon), ...] tuples for h3
    outer_ring = [(coord[1], coord[0]) for coord in plume.coordinates]

    try:
        polygon = h3.LatLngPoly(outer_ring)
        hex_ids = h3.polygon_to_cells(polygon, resolution)
    except Exception as e:
        logger.warning(
            "H3 rasterisation failed for plume at (%.4f, %.4f): %s",
            plume.fire_lat, plume.fire_lon, e,
        )
        return []

    source_label = f"fire @ {plume.fire_lat:.4f},{plume.fire_lon:.4f} T+{plume.hours_ahead:.0f}h"
    cells = []

    for hex_id in hex_ids:
        # h3 v4: cell_to_latlng returns (lat, lon)
        hex_lat, hex_lon = h3.cell_to_latlng(hex_id)
        dist_km = _haversine_km(plume.fire_lat, plume.fire_lon, hex_lat, hex_lon)
        severity = _decay_severity(plume.severity_base, plume.hours_ahead, dist_km)

        if severity >= MIN_SEVERITY_THRESHOLD:
            cells.append(HazardCell(
                h3_index=hex_id,
                severity=round(severity, 4),
                hazard_type="smoke",
                valid_at=plume.valid_at,
                sources=[source_label],
            ))

    return cells


# ─────────────────────────────────────────────────────────────────────────────
# MERGE — combine all hex cells into a single grid, sum overlaps
# ─────────────────────────────────────────────────────────────────────────────

def _merge_hex_grid(cells: list[HazardCell]) -> dict[str, float]:
    """Merge all HazardCells into {h3_index: severity}. Overlapping hexes sum, capped at 1.0."""
    grid: dict[str, float] = {}
    for cell in cells:
        existing = grid.get(cell.h3_index, 0.0)
        grid[cell.h3_index] = min(existing + cell.severity, MAX_SEVERITY)
    return {k: v for k, v in grid.items() if v >= MIN_SEVERITY_THRESHOLD}


# ─────────────────────────────────────────────────────────────────────────────
# AQI OVERLAY — ground-truth smoke readings merged into the hex grid
# ─────────────────────────────────────────────────────────────────────────────

def _overlay_aqi(
    grid: dict[str, float],
    aqi_hazards: list[HazardPoint],
    now: datetime,
    resolution: int = H3_RESOLUTION,
) -> dict[str, float]:
    """
    Merge AQI smoke readings into the existing hex grid.
    AQI is ground-truth — smoke that's already there, not predicted.
    """
    aqi_severity_map = {"low": 0.1, "moderate": 0.3, "high": 0.6, "critical": 0.9}

    for hazard in aqi_hazards:
        severity = aqi_severity_map.get(hazard.severity, 0.2)
        radius_km = hazard.spatial_impact_radius or 10.0

        # k-ring hops: roughly radius / hex edge-to-edge distance
        hex_size_km = 5.16  # approx for resolution 7
        k = max(1, int(radius_km / hex_size_km))

        # h3 v4 API
        centre_hex = h3.latlng_to_cell(hazard.lat, hazard.lon, resolution)
        nearby_hexes = h3.grid_disk(centre_hex, k)

        for hex_id in nearby_hexes:
            existing = grid.get(hex_id, 0.0)
            grid[hex_id] = min(existing + severity, MAX_SEVERITY)

    return grid


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSION — internal SmokePlumes → API-facing HazardPolygons
# ─────────────────────────────────────────────────────────────────────────────

def _plumes_to_polygons(plumes: list[SmokePlume]) -> list[HazardPolygon]:
    """Convert SmokePlumes to HazardPolygon schema objects for the API response."""
    polygons = []
    for plume in plumes:
        severity_str = (
            "critical" if plume.severity_base >= 0.8 else
            "high"     if plume.severity_base >= 0.5 else
            "moderate" if plume.severity_base >= 0.2 else
            "low"
        )
        polygons.append(HazardPolygon(
            hazard_type="smoke",
            severity=severity_str,
            valid_at=plume.valid_at,
            coordinates=plume.coordinates,
            source_fire=f"{plume.fire_lat:.4f},{plume.fire_lon:.4f}",
        ))
    return polygons


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def generate_hazard_field(
    fires:         list[HazardPoint],
    wind_vectors:  list[WindVector],
    aqi_hazards:   list[HazardPoint],
    time_horizons: list[float] = TIME_HORIZONS_HOURS,
) -> tuple[list[HazardPolygon], dict[str, float]]:
    """
    Master L2 function. Takes raw L1 data, returns hazard polygons + hex grid.

    Args:
        fires:         HazardPoints with hazard_type="wildfire" from FIRMS.
        wind_vectors:  WindVectors from Open-Meteo (sampled along route).
        aqi_hazards:   HazardPoints with hazard_type="smoke" from AQI.
        time_horizons: Hours ahead to project (default [0, 1, 2, 4, 6]).

    Returns:
        (polygons, hex_grid) where:
            polygons  = list[HazardPolygon] for frontend map
            hex_grid  = {h3_index: severity} for L3 scoring
    """
    logger.info(
        "generate_hazard_field() — %d fires, %d wind vectors, %d AQI hazards, horizons=%s",
        len(fires), len(wind_vectors), len(aqi_hazards), time_horizons,
    )

    now = datetime.utcnow()

    # Edge case: no fires — still overlay AQI (smoke can exist without nearby fires)
    if not fires:
        logger.info("No fires — overlaying AQI only.")
        grid = _overlay_aqi({}, aqi_hazards, now)
        return [], grid

    if not wind_vectors:
        logger.warning("No wind vectors — cannot generate directional plumes.")
        return [], {}

    all_plumes: list[SmokePlume] = []
    all_cells:  list[HazardCell] = []

    for fire in fires:
        # Interpolate wind at fire's location from nearby route samples
        try:
            wind = interpolate_wind(fire.lat, fire.lon, wind_vectors, n_nearest=3)
        except ValueError as e:
            logger.warning("Skipping fire at (%.4f, %.4f): %s", fire.lat, fire.lon, e)
            continue

        severity_base = _frp_to_severity(fire)

        logger.info(
            "Fire (%.4f, %.4f) — severity=%.2f, wind=%.1f km/h from %.1f°",
            fire.lat, fire.lon, severity_base,
            wind["speed_kmh"], wind["direction_deg"],
        )

        # Generate a plume at each time horizon
        for hours in time_horizons:
            plume = _generate_plume(fire, wind, hours, now, severity_base)
            all_plumes.append(plume)
            all_cells.extend(_rasterise_plume(plume))

    # Merge all hex cells → single grid, then overlay AQI
    hex_grid = _merge_hex_grid(all_cells)
    hex_grid = _overlay_aqi(hex_grid, aqi_hazards, now)

    # Convert internal plumes to API-facing schema
    polygons = _plumes_to_polygons(all_plumes)

    logger.info(
        "Hazard field complete — %d polygons, %d H3 hexes.",
        len(polygons), len(hex_grid),
    )

    return polygons, hex_grid


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL TEST — run with: python -m services.hazard_field
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
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

    polygons, hex_grid = generate_hazard_field(mock_fires, mock_wind, mock_aqi)

    print(f"\nGenerated {len(polygons)} hazard polygons")
    print(f"H3 grid contains {len(hex_grid)} hexes")
    if hex_grid:
        top = sorted(hex_grid.items(), key=lambda x: x[1], reverse=True)[:3]
        print("Top 3 highest-severity hexes:")
        for hex_id, sev in top:
            print(f"  {hex_id}: {sev:.3f}")