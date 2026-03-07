"""
services/hazard_field.py

L2 — Hazard Field Generator

PURPOSE:
    Takes raw data from L1 (fire hotspots, wind vectors, AQI readings)
    and produces two things:

    1. HazardPolygons — time-stamped smoke zones for the frontend map
       ("at 2pm, this area will have dangerous smoke")

    2. H3 hex grid — a fast-lookup grid of danger scores for L3
       (L3 checks each route segment's hex → instant risk score)

PIPELINE OVERVIEW:
    L1 fires + wind + AQI
        │
        ▼
    ┌──────────────────────────────────┐
    │  generate_hazard_field()         │
    │                                  │
    │  1. Interpolate wind at fires    │  ← DONE (IDW from wind_interpolation)
    │  2. Generate plume per fire      │  ← DONE
    │  3. Apply severity decay         │  ← DONE
    │  4. Project plumes over time     │  ← DONE
    │  5. Rasterise onto H3 hex grid   │  ← DONE
    │  6. Merge plumes + overlay AQI   │  ← DONE
    └──────────────────────────────────┘
        │
        ▼
    HazardPolygons + H3 hex grid → sent to L3

CONSUMED BY:
    - routers/hazard.py — the HTTP endpoint
    - L3 risk scorer — reads the hex grid to score route segments
"""

import math
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

import h3

from models.schemas import HazardPoint, HazardPolygon, WindVector
from services.wind_interpolation import interpolate_wind

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SmokePlume:
    """
    One fire's projected smoke zone at a specific point in time.

    Attributes:
        fire_lat, fire_lon:  Original fire location (source of the plume).
        valid_at:            The future timestamp this plume represents.
        hours_ahead:         How many hours from now (0 = current conditions).
        severity_base:       0.0–1.0 base severity from fire's FRP/confidence.
        coordinates:         [[lon, lat], ...] — the polygon ring (GeoJSON order).
        wind_speed_kmh:      Wind speed used to generate this plume.
        wind_direction_deg:  Wind direction used (where wind comes FROM).
    """
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
    """
    One hexagon on the H3 grid with an assigned danger score.

    Attributes:
        h3_index:    The H3 hexagon ID string (e.g. "872830b2fffffff").
        severity:    0.0–1.0 danger score. Capped at MAX_SEVERITY.
        hazard_type: "wildfire", "smoke", or "combined".
        valid_at:    The future time this cell's severity is valid for.
        sources:     List of contributing sources for debugging.
    """
    h3_index:    str
    severity:    float
    hazard_type: str
    valid_at:    datetime
    sources:     list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Time steps to project smoke forward (hours from now)
TIME_HORIZONS_HOURS: list[float] = [0, 1, 2, 4, 6]

# H3 resolution 7 ≈ 5.16 km² per hex — good balance of precision vs performance
H3_RESOLUTION: int = 7

MAX_SEVERITY: float = 1.0
MIN_SEVERITY_THRESHOLD: float = 0.05

# Base smoke radius (km) per severity tier — expanded by wind over time
BASE_RADIUS_KM = {
    "low":      10.0,
    "moderate": 25.0,
    "high":     50.0,
    "critical": 80.0,
}

# How much FRP contributes to severity (normalised against a large fire ~500 MW)
FRP_SEVERITY_MAX = 500.0


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — FRP → base severity
# ─────────────────────────────────────────────────────────────────────────────

def _frp_to_severity(fire: HazardPoint) -> float:
    """
    Convert a fire's FRP (Fire Radiative Power) into a 0.0–1.0 severity score.
    Falls back to severity string if FRP metadata is missing.
    """
    frp = fire.metadata.get("frp_mw")
    if frp is not None:
        return min(float(frp) / FRP_SEVERITY_MAX, 1.0)

    # Fallback to string severity from FIRMS confidence tiers
    mapping = {"low": 0.2, "moderate": 0.5, "high": 0.8, "critical": 1.0}
    return mapping.get(fire.severity, 0.5)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Geometry: offset a lat/lon point by (dx, dy) in km
# ─────────────────────────────────────────────────────────────────────────────

def _offset_point(lat: float, lon: float, dx_km: float, dy_km: float) -> tuple[float, float]:
    """
    Offset a geographic point by dx_km (east) and dy_km (north).
    Returns (new_lat, new_lon).
    Uses the small-angle flat-earth approximation — accurate enough within ~200km.
    """
    new_lat = lat + (dy_km / 111.0)
    new_lon = lon + (dx_km / (111.0 * math.cos(math.radians(lat))))
    return new_lat, new_lon


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Generate a single smoke plume polygon for one fire at one time step
# ─────────────────────────────────────────────────────────────────────────────

def _generate_plume(
    fire: HazardPoint,
    wind: dict,
    hours_ahead: float,
    now: datetime,
    severity_base: float,
) -> SmokePlume:
    """
    Generate a smoke plume ellipse for one fire at a specific time horizon.

    The plume is an ellipse stretched downwind:
        - Upwind radius   = base_radius (fire's own smoke footprint)
        - Downwind radius = base_radius + drift distance (wind carries smoke forward)
        - Cross-wind radius = base_radius * 0.4 (smoke disperses sideways too)

    The polygon is built as 36 points around the ellipse, rotated to face
    the wind travel direction.

    Args:
        fire:          The fire HazardPoint from FIRMS.
        wind:          Interpolated wind dict from interpolate_wind().
        hours_ahead:   How many hours ahead this plume is projected.
        now:           Current datetime — used to compute valid_at.
        severity_base: 0.0–1.0 base severity score for this fire.

    Returns:
        SmokePlume with coordinates in [[lon, lat], ...] GeoJSON order.
    """
    speed     = wind["speed_kmh"]
    direction = wind["direction_deg"]

    # How far smoke has drifted downwind (km)
    drift_km = speed * hours_ahead

    # Base radius from fire severity
    base_radius = BASE_RADIUS_KM.get(fire.severity, 25.0)

    # Plume dimensions
    downwind_radius  = base_radius + drift_km
    upwind_radius    = base_radius
    crosswind_radius = base_radius * 0.4 + (drift_km * 0.1)

    # Wind travel direction (smoke drifts TO this direction)
    travel_deg = (direction + 180) % 360
    travel_rad = math.radians(travel_deg)

    # Centre of the plume — offset from fire in downwind direction
    # The plume centre moves with the wind; fire stays at origin
    drift_dx = math.sin(travel_rad) * drift_km * 0.5
    drift_dy = math.cos(travel_rad) * drift_km * 0.5
    centre_lat, centre_lon = _offset_point(fire.lat, fire.lon, drift_dx, drift_dy)

    # Build ellipse polygon (36 points = every 10°)
    coords = []
    for angle_deg in range(0, 360, 10):
        angle_rad = math.radians(angle_deg)

        # Ellipse in local coords (x=east, y=north)
        local_x = crosswind_radius * math.sin(angle_rad)
        local_y = (downwind_radius if math.cos(angle_rad) >= 0 else upwind_radius) * math.cos(angle_rad)

        # Rotate ellipse to align with wind direction
        rotated_x = local_x * math.cos(travel_rad) - local_y * math.sin(travel_rad)
        rotated_y = local_x * math.sin(travel_rad) + local_y * math.cos(travel_rad)

        pt_lat, pt_lon = _offset_point(centre_lat, centre_lon, rotated_x, rotated_y)
        coords.append([pt_lon, pt_lat])  # GeoJSON order: [lon, lat]

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
# STEP 4 — Severity decay: score drops with distance from fire centre
# ─────────────────────────────────────────────────────────────────────────────

def _decay_severity(base_severity: float, hours_ahead: float) -> float:
    """
    Reduce severity over time — smoke disperses and dilutes as it travels.

    Uses exponential decay:
        severity(t) = base * e^(-decay_rate * t)

    decay_rate = 0.15 means severity halves roughly every 4.6 hours.
    At T+6h, severity is ~40% of base. At T+0, it's 100%.
    """
    decay_rate = 0.15
    return base_severity * math.exp(-decay_rate * hours_ahead)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Rasterise a plume onto H3 hexes
# ─────────────────────────────────────────────────────────────────────────────

def _rasterise_plume(
    plume: SmokePlume,
    resolution: int = H3_RESOLUTION,
) -> list[HazardCell]:
    """
    Convert a SmokePlume polygon into a list of H3 HazardCells.

    Uses h3.polyfill() to find all hexagons that cover the plume polygon.
    Each hex gets the plume's (time-decayed) severity score.

    Args:
        plume:      The SmokePlume to rasterise.
        resolution: H3 resolution (default 7 ≈ 5km hexes).

    Returns:
        List of HazardCell objects — one per H3 hex inside the plume.
    """
    severity = _decay_severity(plume.severity_base, plume.hours_ahead)

    if severity < MIN_SEVERITY_THRESHOLD:
        return []

    # h3.polyfill expects GeoJSON polygon dict with [lon, lat] coordinates
    geojson_polygon = {
        "type": "Polygon",
        "coordinates": [plume.coordinates],
    }

    try:
        hex_ids = h3.polyfill_geojson(geojson_polygon, resolution)
    except Exception as e:
        logger.warning("H3 polyfill failed for plume at (%.4f, %.4f): %s", plume.fire_lat, plume.fire_lon, e)
        return []

    source_label = f"fire @ {plume.fire_lat:.4f},{plume.fire_lon:.4f} T+{plume.hours_ahead:.0f}h"

    return [
        HazardCell(
            h3_index=hex_id,
            severity=round(severity, 4),
            hazard_type="smoke",
            valid_at=plume.valid_at,
            sources=[source_label],
        )
        for hex_id in hex_ids
    ]


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Merge all HazardCells into a single hex grid dict
# ─────────────────────────────────────────────────────────────────────────────

def _merge_hex_grid(cells: list[HazardCell]) -> dict[str, float]:
    """
    Merge all HazardCells into a single flat dict: { h3_index: severity }.

    When multiple plumes overlap the same hex, severities are summed
    and capped at MAX_SEVERITY (1.0). This means overlapping fire corridors
    compound — which is realistic.

    Args:
        cells: All HazardCells from all plumes across all time steps.

    Returns:
        Dict mapping H3 hex ID → peak severity score.
        Only includes hexes above MIN_SEVERITY_THRESHOLD.
    """
    grid: dict[str, float] = {}

    for cell in cells:
        existing = grid.get(cell.h3_index, 0.0)
        grid[cell.h3_index] = min(existing + cell.severity, MAX_SEVERITY)

    # Filter out negligible hexes
    return {k: v for k, v in grid.items() if v >= MIN_SEVERITY_THRESHOLD}


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Overlay AQI hazards onto the hex grid
# ─────────────────────────────────────────────────────────────────────────────

def _overlay_aqi(
    grid: dict[str, float],
    aqi_hazards: list[HazardPoint],
    now: datetime,
    resolution: int = H3_RESOLUTION,
) -> dict[str, float]:
    """
    Overlay AQI smoke readings onto the existing hex grid.

    AQI gives us ground-truth smoke that's already present — not predicted.
    Each AQI HazardPoint contributes to the hexes within its spatial_impact_radius.

    Args:
        grid:        Existing hex grid from fire plumes.
        aqi_hazards: AQI HazardPoints with hazard_type="smoke".
        now:         Current datetime.
        resolution:  H3 resolution.

    Returns:
        Updated hex grid with AQI contributions merged in.
    """
    aqi_severity_map = {"low": 0.1, "moderate": 0.3, "high": 0.6, "critical": 0.9}

    for hazard in aqi_hazards:
        severity = aqi_severity_map.get(hazard.severity, 0.2)
        radius_km = hazard.spatial_impact_radius or 10.0

        # Find all H3 hexes within the AQI impact radius using k-ring
        # k-ring(k) gives all hexes within k hops — roughly radius / hex_size hops
        hex_size_km = 5.16  # approximate for resolution 7
        k = max(1, int(radius_km / hex_size_km))

        centre_hex = h3.geo_to_h3(hazard.lat, hazard.lon, resolution)
        nearby_hexes = h3.k_ring(centre_hex, k)

        for hex_id in nearby_hexes:
            existing = grid.get(hex_id, 0.0)
            grid[hex_id] = min(existing + severity, MAX_SEVERITY)

    return grid


# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Convert SmokePlumes to HazardPolygons for the frontend
# ─────────────────────────────────────────────────────────────────────────────

def _plumes_to_polygons(plumes: list[SmokePlume]) -> list[HazardPolygon]:
    """
    Convert internal SmokePlume objects into HazardPolygon schema objects
    for the API response and frontend map visualisation.
    """
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
    Master function — the single entry point for all of L2.

    Takes raw L1 data and produces the full hazard field.
    This is what routers/hazard.py will call.

    Args:
        fires:         List of HazardPoints with hazard_type="wildfire" from FIRMS.
        wind_vectors:  List of WindVectors from Open-Meteo (sampled along route).
        aqi_hazards:   List of HazardPoints with hazard_type="smoke" from AQI.
        time_horizons: Hours ahead to project smoke (default: [0, 1, 2, 4, 6]).

    Returns:
        polygons:  List of HazardPolygon objects — one per fire per time step.
                   These go to the frontend for map visualisation.
        hex_grid:  Dict mapping H3 hex IDs to severity scores.
                   e.g. {"872830b2fffffff": 0.85, "872830b3fffffff": 0.42}
                   This goes to L3 for fast route segment scoring.
    """
    logger.info(
        "generate_hazard_field() — %d fires, %d wind vectors, %d AQI hazards, horizons=%s",
        len(fires), len(wind_vectors), len(aqi_hazards), time_horizons,
    )

    now = datetime.utcnow()

    if not fires:
        logger.info("No fires — overlaying AQI only.")
        grid = _overlay_aqi({}, aqi_hazards, now)
        return [], grid

    if not wind_vectors:
        logger.warning("No wind vectors — cannot generate directional plumes.")
        return [], {}

    all_plumes: list[SmokePlume] = []
    all_cells:  list[HazardCell] = []

    # ── For each fire, interpolate wind then generate plumes ──────────────────
    for fire in fires:
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

        # ── Generate plume at each time horizon ───────────────────────────────
        for hours in time_horizons:
            plume = _generate_plume(fire, wind, hours, now, severity_base)
            all_plumes.append(plume)

            # Rasterise onto H3 grid
            cells = _rasterise_plume(plume)
            all_cells.extend(cells)

    # ── Merge all cells into flat hex grid ────────────────────────────────────
    hex_grid = _merge_hex_grid(all_cells)

    # ── Overlay AQI ground-truth smoke readings ───────────────────────────────
    hex_grid = _overlay_aqi(hex_grid, aqi_hazards, now)

    # ── Convert plumes to API-facing HazardPolygons ───────────────────────────
    polygons = _plumes_to_polygons(all_plumes)

    logger.info(
        "Hazard field complete — %d polygons, %d H3 hexes populated.",
        len(polygons), len(hex_grid),
    )

    return polygons, hex_grid


# ── Local test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from datetime import datetime

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
        for hex_id, severity in top:
            print(f"  {hex_id}: {severity:.3f}")