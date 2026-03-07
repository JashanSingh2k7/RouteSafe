"""
services/hazard_field.py

L2 — Hazard Field Generator (scaffold)

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
    │  generate_hazard_field()         │  ← YOU ARE HERE (Step 1: scaffold)
    │                                  │
    │  1. Interpolate wind at fires    │  ← Step 2
    │  2. Generate plume per fire      │  ← Step 3
    │  3. Apply severity decay         │  ← Step 4
    │  4. Project plumes over time     │  ← Step 5
    │  5. Rasterise onto H3 hex grid   │  ← Step 6
    │  6. Merge plumes + overlay AQI   │  ← Step 7
    └──────────────────────────────────┘
        │
        ▼
    HazardPolygons + H3 hex grid → sent to L3

CONSUMED BY:
    - routers/hazard.py (Step 8) — the HTTP endpoint
    - L3 risk scorer — reads the hex grid to score route segments

AUTHORS: [your names here]
"""

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

from models.schemas import HazardPoint, HazardPolygon, WindVector

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL DATA STRUCTURES
#
# These are NOT API-facing. They only live inside L2 to pass data between
# the sub-steps above. The final output uses HazardPolygon from schemas.py.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SmokePlume:
    """
    One fire's projected smoke zone at a specific point in time.

    Think of it this way:
        - You have a fire at (lat, lon).
        - Wind is blowing east at 20 km/h.
        - At T+2 hours, the smoke has drifted ~40 km east.
        - This dataclass holds that projected smoke shape + metadata.

    Created in Step 3 (single-fire plume generator).
    Collected across time steps in Step 5.
    Rasterised onto H3 hexes in Step 6.

    Attributes:
        fire_lat, fire_lon:  Original fire location (source of the plume).
        valid_at:            The future timestamp this plume represents.
        hours_ahead:         How many hours from now (0 = current conditions).
        severity_base:       0.0–1.0 base severity from fire's FRP/confidence.
        coordinates:         [[lon, lat], ...] — the polygon ring (GeoJSON order).
                             This is the smoke zone boundary at this time step.
        wind_speed_kmh:      Wind speed used to generate this plume.
        wind_direction_deg:  Wind direction used (where wind comes FROM).
    """

    fire_lat:           float
    fire_lon:           float
    valid_at:           datetime
    hours_ahead:        float
    severity_base:      float
    coordinates:        list[list[float]]           # [[lon, lat], ...] closed ring
    wind_speed_kmh:     float
    wind_direction_deg: float


@dataclass
class HazardCell:
    """
    One hexagon on the H3 grid with an assigned danger score.

    Instead of checking "is this route point inside a polygon?" (slow),
    L3 converts a route point to its H3 hex ID and looks it up in a
    dictionary (fast — O(1) lookup).

    Created in Step 6 (H3 rasterisation).
    Merged in Step 7 (plume merging).

    Attributes:
        h3_index:     The H3 hexagon ID string (e.g. "872830b2fffffff").
                      This is a globally unique ID for a ~5 km hex on the map.
        severity:     0.0–1.0 danger score. 0 = safe, 1 = maximum danger.
                      When multiple plumes overlap, severities are summed
                      and capped at 1.0 (Step 7).
        hazard_type:  What kind of danger — "wildfire", "smoke", or "combined".
        valid_at:     The future time this cell's severity is valid for.
        sources:      List of contributing sources for debugging/transparency.
                      e.g. ["NASA FIRMS fire @ 51.2,-115.3", "AQI reading"]
    """

    h3_index:    str
    severity:    float
    hazard_type: str
    valid_at:    datetime
    sources:     list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
#
# Tunable parameters for the hazard model. Pulled out here so they're easy
# to find and adjust during testing / demo prep.
# ─────────────────────────────────────────────────────────────────────────────

# Time steps to project smoke forward (in hours from now)
# T+0 = current conditions, T+6 = six hours from now
TIME_HORIZONS_HOURS: list[float] = [0, 1, 2, 4, 6]

# H3 resolution for the hex grid
# Resolution 7 ≈ 5.16 km² per hex — good balance of precision vs performance
# Resolution 8 ≈ 0.74 km² — more precise but ~7x more hexes to process
H3_RESOLUTION: int = 7

# Maximum severity score (cap when merging overlapping plumes)
MAX_SEVERITY: float = 1.0

# Minimum severity to keep in the grid (below this = not worth storing)
# Keeps the hex grid lean — no point telling L3 about negligible smoke
MIN_SEVERITY_THRESHOLD: float = 0.05


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
        A tuple of:
            polygons:  List of HazardPolygon objects — one per fire per time step.
                       These go to the frontend for map visualisation.

            hex_grid:  Dict mapping H3 hex IDs to severity scores.
                       e.g. {"872830b2fffffff": 0.85, "872830b3fffffff": 0.42}
                       This goes to L3 for fast route segment scoring.

    Pipeline (each step is a separate function, built in later steps):
        1. Interpolate wind at each fire's location          (Step 2)
        2. Generate a smoke plume per fire per time step     (Steps 3 + 5)
        3. Compute severity decay from fire centre           (Step 4)
        4. Rasterise all plumes onto H3 hex grid             (Step 6)
        5. Merge overlapping plumes + overlay AQI            (Step 7)
    """

    logger.info(
        "generate_hazard_field() called — %d fires, %d wind vectors, %d AQI hazards, "
        "time horizons=%s",
        len(fires), len(wind_vectors), len(aqi_hazards), time_horizons,
    )

    
    logger.warning("generate_hazard_field() is a scaffold — returning empty results.")
    return [], {}