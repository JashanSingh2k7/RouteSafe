"""
services/hazard_field.py

L2 — Hazard Field Generator

Takes L1 data (fire hotspots, wind vectors, AQI readings) and produces:
  1. HazardPolygons       — time-stamped smoke zones for frontend map
  2. Flat hex grid         — peak danger scores for simple visualization
  3. Time-bucketed grids   — per-time-step grids so L3 scores segments
                             against the correct future time window

Pipeline:
    L1 fires + wind + AQI
        → interpolate wind at each fire
        → generate smoke plume ellipses per fire per time step
        → rasterise plumes onto H3 hex grid with severity decay
        → merge overlapping plumes + overlay AQI ground-truth
        → output HazardPolygons + hex grids

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
    """One H3 hexagon with a danger score."""
    h3_index:    str
    severity:    float                              # 0.0–1.0
    hazard_type: str
    valid_at:    datetime
    hours_ahead: float                              # which time bucket this belongs to
    sources:     list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

TIME_HORIZONS_HOURS: list[float] = [0, 1, 2, 4, 6]
H3_RESOLUTION: int = 7 # ~5.16 km² per hex
MAX_SEVERITY: float = 1.0
MIN_SEVERITY_THRESHOLD: float = 0.02              # lowered from 0.05 — small fires still matter

BASE_RADIUS_KM = {
    "low": 10.0, "moderate": 25.0, "high": 50.0, "critical": 80.0,
}

FRP_SEVERITY_MAX = 500.0
TIME_DECAY_RATE = 0.15
DISTANCE_DECAY_RATE = 0.04

# Minimum severity floor per tier — a detected fire is ALWAYS a hazard.
# Without this, a 3 MW fire gets severity 0.006 (invisible).
# VIIRS satellite confirmed it's burning — we must show it.
SEVERITY_FLOOR = {
    "low":      0.15,
    "moderate": 0.35,
    "high":     0.65,
    "critical": 0.85,
}

# Calm wind fallback — used when Open-Meteo wind data is unavailable.
# Produces circular (non-stretched) plumes around each fire.
CALM_WIND: dict = {"speed_kmh": 5.0, "direction_deg": 0.0, "gusts_kmh": None}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _frp_to_severity(fire: HazardPoint) -> float:
    """
    FRP (MW) → 0.0 to 1.0 severity, with a minimum floor per tier.

    Problem solved: A 3 MW prescribed burn in Florida had FRP/500 = 0.006,
    which fell below MIN_SEVERITY_THRESHOLD (0.05) and produced ZERO hexes.
    But VIIRS confirmed it's a real fire — it must show on the map.

    Fix: Use FRP for scaling within the tier, but enforce a floor so that
    any satellite-confirmed fire always produces visible hazard.
    """
    # Floor based on the severity string (always available from FIRMS)
    floor = SEVERITY_FLOOR.get(fire.severity, 0.15)

    frp = fire.metadata.get("frp_mw")
    if frp is not None:
        frp_severity = min(float(frp) / FRP_SEVERITY_MAX, 1.0)
        # Use whichever is higher: the FRP-derived value or the tier floor
        return max(frp_severity, floor)

    # No FRP available — use the tier mapping directly
    mapping = {"low": 0.2, "moderate": 0.5, "high": 0.8, "critical": 1.0}
    return mapping.get(fire.severity, 0.5)


def _offset_point(lat: float, lon: float, dx_km: float, dy_km: float) -> tuple[float, float]:
    """Offset lat/lon by dx_km east and dy_km north. Flat-earth approx."""
    new_lat = lat + (dy_km / 111.0)
    new_lon = lon + (dx_km / (111.0 * math.cos(math.radians(lat))))
    return new_lat, new_lon


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
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
# PLUME GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def _generate_plume( fire: HazardPoint, wind: dict, hours_ahead: float, now: datetime, severity_base: float, ) -> SmokePlume:
    """Build a wind-stretched ellipse for one fire at one time horizon."""

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


# ─────────────────────────────────────────────────────────────────────────────
# SEVERITY DECAY
# ─────────────────────────────────────────────────────────────────────────────

def _decay_severity(base_severity: float, hours_ahead: float, distance_km: float = 0.0) -> float:
    """Severity drops with time (dilution) and distance from fire centre."""
    time_factor = math.exp(-TIME_DECAY_RATE * hours_ahead)
    distance_factor = math.exp(-DISTANCE_DECAY_RATE * distance_km)
    return base_severity * time_factor * distance_factor


# ─────────────────────────────────────────────────────────────────────────────
# H3 RASTERISATION
# ─────────────────────────────────────────────────────────────────────────────

def _rasterise_plume(plume: SmokePlume, resolution: int = H3_RESOLUTION) -> list[HazardCell]:
    """Plume polygon → H3 hex cells with distance-decayed severity."""

    time_decayed = _decay_severity(plume.severity_base, plume.hours_ahead)
    if time_decayed < MIN_SEVERITY_THRESHOLD:
        return []

    outer_ring = [(coord[1], coord[0]) for coord in plume.coordinates]
    try:
        polygon = h3.LatLngPoly(outer_ring)
        hex_ids = h3.polygon_to_cells(polygon, resolution)
    except Exception as e:
        logger.warning("H3 rasterisation failed at (%.4f, %.4f): %s", plume.fire_lat, plume.fire_lon, e)
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


# ─────────────────────────────────────────────────────────────────────────────
# MERGE + AQI OVERLAY
# ─────────────────────────────────────────────────────────────────────────────

def _merge_hex_grid(cells: list[HazardCell]) -> dict[str, float]:
    """Merge cells into {h3_index: severity}. Overlaps sum, capped at 1.0."""

    grid: dict[str, float] = {}
    for cell in cells:
        grid[cell.h3_index] = min(grid.get(cell.h3_index, 0.0) + cell.severity, MAX_SEVERITY)
    return {k: v for k, v in grid.items() if v >= MIN_SEVERITY_THRESHOLD}


def _overlay_aqi(
    grid: dict[str, float], aqi_hazards: list[HazardPoint],
    now: datetime, resolution: int = H3_RESOLUTION,
) -> dict[str, float]:
    """Merge AQI ground-truth smoke readings into the hex grid."""
    aqi_severity_map = {"low": 0.1, "moderate": 0.3, "high": 0.6, "critical": 0.9}
    for hazard in aqi_hazards:
        severity = aqi_severity_map.get(hazard.severity, 0.2)
        radius_km = hazard.spatial_impact_radius or 10.0
        k = max(1, int(radius_km / 5.16))
        centre_hex = h3.latlng_to_cell(hazard.lat, hazard.lon, resolution)
        for hex_id in h3.grid_disk(centre_hex, k):
            grid[hex_id] = min(grid.get(hex_id, 0.0) + severity, MAX_SEVERITY)
    return grid


def _plumes_to_polygons(plumes: list[SmokePlume]) -> list[HazardPolygon]:
    """Convert internal SmokePlumes to API-facing HazardPolygon schema."""
    
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
    """
    Master L2 function.

    Returns:
        (polygons, flat_grid, grids_by_time)
            polygons      → frontend map visualization
            flat_grid     → {hex: peak_severity} across all time steps
            grids_by_time → {hours_ahead: {hex: severity}} for L3 time-aware scoring
    """
    logger.info(
        "generate_hazard_field() — %d fires, %d wind vectors, %d AQI, horizons=%s",
        len(fires), len(wind_vectors), len(aqi_hazards), time_horizons,
    )
    now = datetime.utcnow()

    if not fires:
        logger.info("No fires — overlaying AQI only.")
        aqi_grid = _overlay_aqi({}, aqi_hazards, now)
        return [], aqi_grid, {0: aqi_grid}

    # ── FIX: fallback to calm wind when wind data is unavailable ──────
    # Previously this returned [], {}, {} — dropping ALL fire hazard data.
    # A fire without wind data is still a fire. Use calm-wind circular plumes.
    use_calm_wind = False
    if not wind_vectors:
        logger.warning(
            "No wind vectors available — using calm-wind fallback. "
            "Plumes will be circular (no directional stretch)."
        )
        use_calm_wind = True

    all_plumes: list[SmokePlume] = []
    cells_by_time: dict[float, list[HazardCell]] = {h: [] for h in time_horizons}

    for fire in fires:
        # Get wind for this fire's location
        if use_calm_wind:
            wind = CALM_WIND
        else:
            try:
                wind = interpolate_wind(fire.lat, fire.lon, wind_vectors, n_nearest=3)
            except ValueError as e:
                logger.warning(
                    "Wind interpolation failed for fire at (%.4f, %.4f): %s — using calm fallback",
                    fire.lat, fire.lon, e,
                )
                wind = CALM_WIND

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
            cells = _rasterise_plume(plume)
            cells_by_time[hours].extend(cells)

    # Build time-bucketed grids
    grids_by_time: dict[float, dict[str, float]] = {}
    for hours, cells in cells_by_time.items():
        grids_by_time[hours] = _merge_hex_grid(cells)

    # AQI is current conditions → T+0 only
    grids_by_time[0] = _overlay_aqi(grids_by_time.get(0, {}), aqi_hazards, now)

    # Flat grid = peak severity per hex across all time steps (for frontend)
    flat_grid: dict[str, float] = {}
    for t_grid in grids_by_time.values():
        for hex_id, sev in t_grid.items():
            flat_grid[hex_id] = max(flat_grid.get(hex_id, 0.0), sev)

    polygons = _plumes_to_polygons(all_plumes)

    logger.info(
        "Hazard field complete — %d polygons, %d flat hexes, %d time buckets.",
        len(polygons), len(flat_grid), len(grids_by_time),
    )
    return polygons, flat_grid, grids_by_time


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL TEST
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

    polygons, flat_grid, grids_by_time = generate_hazard_field(mock_fires, mock_wind, mock_aqi)

    print(f"\nGenerated {len(polygons)} hazard polygons")
    print(f"Flat grid: {len(flat_grid)} hexes")
    for t, grid in sorted(grids_by_time.items()):
        print(f"  T+{t:.0f}h: {len(grid)} hexes")
    if flat_grid:
        top = sorted(flat_grid.items(), key=lambda x: x[1], reverse=True)[:3]
        print("Top 3 severity hexes:")
        for hex_id, sev in top:
            print(f"  {hex_id}: {sev:.3f}")