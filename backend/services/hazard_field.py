"""
services/hazard_field.py

L2 — Hazard Field Generator

Takes L1 data (fire hotspots, wind vectors, AQI readings) and produces:
  1. HazardPolygons       — time-stamped smoke zones for frontend map
  2. Flat hex grid         — peak danger scores for simple visualization
  3. Time-bucketed grids   — per-time-step grids so L3 scores segments
                             against the correct future time window

Consumed by: routers/scoring.py, L3 route scorer
"""

import math
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import h3
from models.schemas import HazardPoint, HazardPolygon, WindVector
from services.wind_interpolation import interpolate_wind

logger = logging.getLogger(__name__)


@dataclass
class SmokePlume:
    fire_lat:           float
    fire_lon:           float
    valid_at:           datetime
    hours_ahead:        float
    severity_base:      float
    coordinates:        list[list[float]]
    wind_speed_kmh:     float
    wind_direction_deg: float


@dataclass
class HazardCell:
    h3_index:    str
    severity:    float
    hazard_type: str
    valid_at:    datetime
    hours_ahead: float
    sources:     list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

TIME_HORIZONS_HOURS: list[float] = [0, 1, 2, 4, 6]
H3_RESOLUTION: int = 7
MAX_SEVERITY: float = 1.0
MIN_SEVERITY_THRESHOLD: float = 0.02

BASE_RADIUS_KM = {
    "low": 10.0, "moderate": 25.0, "high": 50.0, "critical": 80.0,
}

FRP_SEVERITY_MAX = 500.0
TIME_DECAY_RATE = 0.15
DISTANCE_DECAY_RATE = 0.04

SEVERITY_FLOOR = {
    "low":      0.15,
    "moderate": 0.35,
    "high":     0.65,
    "critical": 0.85,
}

# Calm wind fallback — produces roughly circular plumes with slight drift
CALM_WIND: dict = {"speed_kmh": 5.0, "direction_deg": 0.0, "gusts_kmh": None}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _frp_to_severity(fire: HazardPoint) -> float:
    floor = SEVERITY_FLOOR.get(fire.severity, 0.15)
    frp = fire.metadata.get("frp_mw")
    if frp is not None:
        frp_severity = min(float(frp) / FRP_SEVERITY_MAX, 1.0)
        return max(frp_severity, floor)
    mapping = {"low": 0.2, "moderate": 0.5, "high": 0.8, "critical": 1.0}
    return mapping.get(fire.severity, 0.5)


def _offset_point(lat: float, lon: float, dx_km: float, dy_km: float) -> tuple[float, float]:
    new_lat = lat + (dy_km / 111.0)
    new_lon = lon + (dx_km / (111.0 * math.cos(math.radians(lat))))
    return new_lat, new_lon


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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


def _interpolate_wind_safe(lat: float, lon: float, wind_vectors: list[WindVector]) -> dict:
    """
    Safely interpolate wind at a location. Returns CALM_WIND if interpolation
    fails for any reason (no vectors, too far, etc).
    """
    if not wind_vectors:
        return CALM_WIND
    try:
        return interpolate_wind(lat, lon, wind_vectors, n_nearest=3)
    except (ValueError, Exception) as e:
        logger.debug("Wind interpolation failed at (%.4f, %.4f): %s — using calm wind.", lat, lon, e)
        return CALM_WIND


def _generate_plume(fire, wind, hours_ahead, now, severity_base):
    speed = wind["speed_kmh"]
    direction = wind["direction_deg"]
    drift_km = speed * hours_ahead
    base_radius = BASE_RADIUS_KM.get(fire.severity, 25.0)

    downwind_radius  = base_radius + drift_km
    upwind_radius    = base_radius
    crosswind_radius = base_radius * 0.4 + (drift_km * 0.1)

    travel_deg = (direction + 180) % 360
    travel_rad = math.radians(travel_deg)

    drift_dx = math.sin(travel_rad) * drift_km * 0.5
    drift_dy = math.cos(travel_rad) * drift_km * 0.5
    centre_lat, centre_lon = _offset_point(fire.lat, fire.lon, drift_dx, drift_dy)

    coords = []
    for angle_deg in range(0, 360, 10):
        angle_rad = math.radians(angle_deg)
        local_x = crosswind_radius * math.sin(angle_rad)
        local_y = (
            downwind_radius if math.cos(angle_rad) >= 0 else upwind_radius
        ) * math.cos(angle_rad)

        rotated_x = local_x * math.cos(travel_rad) - local_y * math.sin(travel_rad)
        rotated_y = local_x * math.sin(travel_rad) + local_y * math.cos(travel_rad)

        pt_lat, pt_lon = _offset_point(centre_lat, centre_lon, rotated_x, rotated_y)
        coords.append([pt_lon, pt_lat])

    coords.append(coords[0])

    return SmokePlume(
        fire_lat=fire.lat, fire_lon=fire.lon,
        valid_at=now + timedelta(hours=hours_ahead),
        hours_ahead=hours_ahead, severity_base=severity_base,
        coordinates=coords,
        wind_speed_kmh=speed, wind_direction_deg=direction,
    )


def _decay_severity(base_severity, hours_ahead, distance_km=0.0):
    time_factor = math.exp(-TIME_DECAY_RATE * hours_ahead)
    distance_factor = math.exp(-DISTANCE_DECAY_RATE * distance_km)
    return base_severity * time_factor * distance_factor


def _rasterise_plume(plume, resolution=H3_RESOLUTION):
    time_decayed = _decay_severity(plume.severity_base, plume.hours_ahead)
    if time_decayed < MIN_SEVERITY_THRESHOLD:
        return []

    outer_ring = [(coord[1], coord[0]) for coord in plume.coordinates]
    try:
        polygon = h3.LatLngPoly(outer_ring)
        hex_ids = h3.polygon_to_cells(polygon, resolution)
    except Exception as e:
        logger.warning("H3 rasterisation failed: %s", e)
        return []

    source_label = f"fire @ {plume.fire_lat:.4f},{plume.fire_lon:.4f} T+{plume.hours_ahead:.0f}h"
    cells = []
    for hex_id in hex_ids:
        hex_lat, hex_lon = h3.cell_to_latlng(hex_id)
        dist_km = _haversine_km(plume.fire_lat, plume.fire_lon, hex_lat, hex_lon)
        severity = _decay_severity(plume.severity_base, plume.hours_ahead, dist_km)

        if severity >= MIN_SEVERITY_THRESHOLD:
            cells.append(HazardCell(
                h3_index=hex_id, severity=round(severity, 4),
                hazard_type="smoke", valid_at=plume.valid_at,
                hours_ahead=plume.hours_ahead, sources=[source_label],
            ))
    return cells


def _merge_hex_grid(cells):
    grid = {}
    for cell in cells:
        grid[cell.h3_index] = min(grid.get(cell.h3_index, 0.0) + cell.severity, MAX_SEVERITY)
    return {k: v for k, v in grid.items() if v >= MIN_SEVERITY_THRESHOLD}


def _overlay_aqi(grid, aqi_hazards, now, resolution=H3_RESOLUTION):
    """
    Merge AQI smoke readings into the hex grid.
    AQI is ground-truth — smoke that's already there, not predicted.
    """
    aqi_severity_map = {"low": 0.1, "moderate": 0.3, "high": 0.6, "critical": 0.9}
    for hazard in aqi_hazards:
        severity = aqi_severity_map.get(hazard.severity, 0.2)
        radius_km = hazard.spatial_impact_radius or 10.0
        k = max(1, int(radius_km / 5.16))
        centre_hex = h3.latlng_to_cell(hazard.lat, hazard.lon, resolution)
        for hex_id in h3.grid_disk(centre_hex, k):
            grid[hex_id] = min(grid.get(hex_id, 0.0) + severity, MAX_SEVERITY)
    return grid


def _plumes_to_polygons(plumes):
    polygons = []
    for plume in plumes:
        severity_str = (
            "critical" if plume.severity_base >= 0.8 else
            "high"     if plume.severity_base >= 0.5 else
            "moderate" if plume.severity_base >= 0.2 else
            "low"
        )
        polygons.append(HazardPolygon(
            hazard_type="smoke", severity=severity_str,
            valid_at=plume.valid_at, coordinates=plume.coordinates,
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
) -> tuple[list[HazardPolygon], dict[str, float], dict[float, dict[str, float]]]:
    logger.info(
        "generate_hazard_field() — %d fires, %d wind vectors, %d AQI, horizons=%s",
        len(fires), len(wind_vectors), len(aqi_hazards), time_horizons,
    )
    now = datetime.utcnow()

    # ── No fires: AQI overlay only ────────────────────────────────────────
    # AQI is ground-truth smoke, applies to ALL time horizons since it's
    # already in the air. A segment 4 hours into the trip still drives
    # through the same AQI reading.
    if not fires:
        logger.info("No fires — overlaying AQI only.")
        aqi_grid = _overlay_aqi({}, aqi_hazards, now)
        # Same AQI grid for every time horizon — smoke is already there
        grids_by_time = {h: dict(aqi_grid) for h in time_horizons}
        return [], aqi_grid, grids_by_time

    # ── Build plumes per fire per time horizon ────────────────────────────
    all_plumes = []
    cells_by_time = {h: [] for h in time_horizons}

    for fire in fires:
        wind = _interpolate_wind_safe(fire.lat, fire.lon, wind_vectors)
        severity_base = _frp_to_severity(fire)

        logger.info(
            "Fire (%.4f, %.4f) — severity=%.3f (tier=%s, frp=%s), wind=%.1f km/h from %.1f°",
            fire.lat, fire.lon, severity_base, fire.severity,
            fire.metadata.get("frp_mw", "N/A"),
            wind["speed_kmh"], wind["direction_deg"],
        )

        for hours in time_horizons:
            plume = _generate_plume(fire, wind, hours, now, severity_base)
            all_plumes.append(plume)
            cells_by_time[hours].extend(_rasterise_plume(plume))

    # ── Build per-time grids ──────────────────────────────────────────────
    grids_by_time = {}
    for hours, cells in cells_by_time.items():
        grids_by_time[hours] = _merge_hex_grid(cells)

    # ── Overlay AQI on ALL time buckets ───────────────────────────────────
    # AQI is measured smoke that's already present. It doesn't disappear
    # at T+2h just because our fire plumes change shape.
    for hours in time_horizons:
        grids_by_time[hours] = _overlay_aqi(
            grids_by_time.get(hours, {}), aqi_hazards, now,
        )

    # ── Flat grid: peak severity across all time steps ────────────────────
    flat_grid = {}
    for t_grid in grids_by_time.values():
        for hex_id, sev in t_grid.items():
            flat_grid[hex_id] = max(flat_grid.get(hex_id, 0.0), sev)

    polygons = _plumes_to_polygons(all_plumes)

    logger.info(
        "Hazard field complete — %d polygons, %d flat hexes, %d time buckets.",
        len(polygons), len(flat_grid), len(grids_by_time),
    )
    return polygons, flat_grid, grids_by_time