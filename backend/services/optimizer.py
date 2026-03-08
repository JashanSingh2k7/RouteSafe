"""
services/optimizer.py

L4 — Route Optimizer

Consumes L3 scored segments + L2 hazard grids and generates avoidance
waypoints that steer the route through minimum-risk corridors.

Algorithm (iterative greedy with hex-grid pathfinding):
    1. Identify contiguous high-risk clusters from scored segments
    2. For the worst cluster, extract entry/exit points
    3. Run Dijkstra on the H3 hex grid from entry→exit, weighted by severity
    4. Convert the minimum-risk hex path into a lat/lon waypoint
    5. Re-score the adjusted route and repeat until acceptable or max iterations

Why H3 Dijkstra instead of random lateral offsets:
    - The hazard field IS the H3 grid. Pathfinding on it directly means we
      find the actual minimum-risk corridor, not a guess.
    - Plumes are asymmetric (wind-stretched). Pushing perpendicular might
      route INTO the smoke. Dijkstra respects the real shape.
    - O(N log N) on hex count — fast enough for real-time use.

Consumed by: routers/scoring.py (future), routers/optimizer.py (endpoint)
"""

import math
import heapq
import logging
from dataclasses import dataclass, field
from typing import Optional

import h3

from models.schemas import RouteSegment, ScoredSegment, OptimizedRoute
from services.hazard_field import H3_RESOLUTION, TIME_HORIZONS_HOURS
from services.route_scorer import (
    score_route,
    RISK_THRESHOLDS,
    _haversine_km,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Segments with risk >= this trigger avoidance
AVOIDANCE_THRESHOLD: float = RISK_THRESHOLDS["moderate"]  # 0.40

# Merge segments into a cluster if gap between them is ≤ this many indices
CLUSTER_GAP_TOLERANCE: int = 2

# Dijkstra search radius: how many hex rings outward from the route to explore
# At res 7 (~2.6 km edge), 12 rings ≈ 31 km lateral search
SEARCH_RINGS: int = 12

# Max optimisation iterations (each fixes the worst remaining cluster)
MAX_ITERATIONS: int = 5

# If re-routed distance exceeds original by this factor, abandon that waypoint
MAX_DETOUR_FACTOR: float = 2.5

# Severity cost floor — even "clean" hexes have a small traversal cost
# to prefer shorter paths when severity is equal
BASE_HEX_COST: float = 0.01

# Waypoint placement: how far before/after the hazard zone to anchor
ANCHOR_BUFFER_KM: float = 5.0


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RiskCluster:
    """A contiguous group of high-risk segments."""
    start_index:    int
    end_index:      int
    peak_risk:      float
    avg_risk:       float
    entry_lat:      float
    entry_lon:      float
    exit_lat:       float
    exit_lon:       float
    segment_count:  int


@dataclass(order=True)
class _DijkstraNode:
    """Priority queue entry for hex-grid pathfinding."""
    cost: float
    hex_id: str = field(compare=False)
    parent: Optional[str] = field(default=None, compare=False)


# ─────────────────────────────────────────────────────────────────────────────
# CLUSTER DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _find_risk_clusters(
    segments: list[ScoredSegment],
    threshold: float = AVOIDANCE_THRESHOLD,
    gap_tolerance: int = CLUSTER_GAP_TOLERANCE,
) -> list[RiskCluster]:
    """
    Group consecutive high-risk segments into clusters.

    Segments within `gap_tolerance` indices of each other are merged,
    so a single clean segment sandwiched between two hot zones doesn't
    split the cluster (the waypoint needs to go around the whole thing).
    """
    hot_indices = [s.index for s in segments if s.risk_score >= threshold]
    if not hot_indices:
        return []

    # Build index → segment lookup
    seg_map = {s.index: s for s in segments}

    # Merge nearby hot indices into clusters
    clusters_raw: list[list[int]] = []
    current_group: list[int] = [hot_indices[0]]

    for idx in hot_indices[1:]:
        if idx - current_group[-1] <= gap_tolerance:
            current_group.append(idx)
        else:
            clusters_raw.append(current_group)
            current_group = [idx]
    clusters_raw.append(current_group)

    # Convert to RiskCluster objects
    clusters: list[RiskCluster] = []
    for group in clusters_raw:
        group_segs = [seg_map[i] for i in group if i in seg_map]
        if not group_segs:
            continue

        risks = [s.risk_score for s in group_segs]

        # Entry: start of first segment in cluster (with buffer back 1 if possible)
        first_idx = group[0]
        entry_seg = seg_map.get(max(first_idx - 1, 0), group_segs[0])

        # Exit: end of last segment in cluster (with buffer forward 1 if possible)
        last_idx = group[-1]
        max_idx = max(seg_map.keys())
        exit_seg = seg_map.get(min(last_idx + 1, max_idx), group_segs[-1])

        clusters.append(RiskCluster(
            start_index=first_idx,
            end_index=last_idx,
            peak_risk=max(risks),
            avg_risk=sum(risks) / len(risks),
            entry_lat=entry_seg.start_lat,
            entry_lon=entry_seg.start_lon,
            exit_lat=exit_seg.end_lat,
            exit_lon=exit_seg.end_lon,
            segment_count=len(group_segs),
        ))

    # Sort by peak risk descending — fix worst cluster first
    clusters.sort(key=lambda c: c.peak_risk, reverse=True)
    return clusters


# ─────────────────────────────────────────────────────────────────────────────
# H3 HEX-GRID DIJKSTRA
# ─────────────────────────────────────────────────────────────────────────────

def _hex_severity(hex_id: str, hex_grid: dict[str, float]) -> float:
    """Look up severity for a hex, defaulting to 0 (clean air)."""
    return hex_grid.get(hex_id, 0.0)


def _dijkstra_hex_path(
    start_hex: str,
    goal_hex: str,
    hex_grid: dict[str, float],
    max_rings: int = SEARCH_RINGS,
) -> Optional[list[str]]:
    """
    Shortest-cost path from start_hex to goal_hex on the H3 grid.

    Edge cost = severity of the destination hex + BASE_HEX_COST.
    This means the pathfinder naturally routes through clean hexes.

    We limit the search space to hexes within `max_rings` of the midpoint
    between start and goal to keep it bounded.

    Returns:
        List of H3 hex IDs from start to goal, or None if no path found.
    """
    if start_hex == goal_hex:
        return [start_hex]

    # Build search boundary: all hexes within max_rings of the midpoint
    # plus rings around start and goal to ensure connectivity
    mid_lat = (h3.cell_to_latlng(start_hex)[0] + h3.cell_to_latlng(goal_hex)[0]) / 2
    mid_lon = (h3.cell_to_latlng(start_hex)[1] + h3.cell_to_latlng(goal_hex)[1]) / 2
    mid_hex = h3.latlng_to_cell(mid_lat, mid_lon, H3_RESOLUTION)

    # Distance in hex rings between start and goal
    try:
        direct_dist = h3.grid_distance(start_hex, goal_hex)
    except h3.H3ResDomainError:
        # Fallback: estimate from haversine
        s_ll = h3.cell_to_latlng(start_hex)
        g_ll = h3.cell_to_latlng(goal_hex)
        dist_km = _haversine_km(s_ll[0], s_ll[1], g_ll[0], g_ll[1])
        direct_dist = int(dist_km / 2.6) + 1  # ~2.6 km per hex at res 7

    # Search radius: enough to go around the hazard zone
    search_radius = max(max_rings, direct_dist + 6)

    # Cap to avoid blowing up memory on very long routes
    search_radius = min(search_radius, 40)

    allowed_hexes = set(h3.grid_disk(mid_hex, search_radius))
    # Ensure start/goal are reachable
    allowed_hexes.update(h3.grid_disk(start_hex, 4))
    allowed_hexes.update(h3.grid_disk(goal_hex, 4))

    # Dijkstra
    dist_map: dict[str, float] = {start_hex: 0.0}
    parent_map: dict[str, Optional[str]] = {start_hex: None}
    pq: list[_DijkstraNode] = [_DijkstraNode(cost=0.0, hex_id=start_hex)]
    visited: set[str] = set()

    while pq:
        node = heapq.heappop(pq)

        if node.hex_id in visited:
            continue
        visited.add(node.hex_id)

        if node.hex_id == goal_hex:
            # Reconstruct path
            path = []
            current = goal_hex
            while current is not None:
                path.append(current)
                current = parent_map[current]
            path.reverse()
            return path

        for neighbor in h3.grid_disk(node.hex_id, 1):
            if neighbor == node.hex_id or neighbor in visited:
                continue
            if neighbor not in allowed_hexes:
                continue

            sev = _hex_severity(neighbor, hex_grid)
            # Cost: severity² to strongly penalise hot hexes + base cost for distance
            edge_cost = (sev ** 2) + BASE_HEX_COST
            new_cost = node.cost + edge_cost

            if new_cost < dist_map.get(neighbor, float("inf")):
                dist_map[neighbor] = new_cost
                parent_map[neighbor] = node.hex_id
                heapq.heappush(pq, _DijkstraNode(cost=new_cost, hex_id=neighbor))

    logger.warning("Dijkstra found no path from %s to %s", start_hex, goal_hex)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# WAYPOINT EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def _hex_path_to_waypoints(
    hex_path: list[str],
    max_waypoints: int = 3,
) -> list[dict[str, float]]:
    """
    Convert a hex path into a small set of waypoints for Google Directions.

    Google allows max 25 waypoints. We want 1–3 per hazard zone —
    enough to steer the route, not so many that the API chokes.

    Strategy: sample evenly along the hex path (skip start/end since
    those are the existing route entry/exit).
    """
    if len(hex_path) <= 2:
        return []

    # Exclude first and last hex (those are on the original route)
    inner = hex_path[1:-1]
    if not inner:
        return []

    # Pick evenly spaced waypoints from the inner path
    n = min(max_waypoints, len(inner))
    step = len(inner) / (n + 1)
    indices = [int(step * (i + 1)) for i in range(n)]
    # Clamp
    indices = [min(i, len(inner) - 1) for i in indices]

    waypoints = []
    for idx in indices:
        lat, lon = h3.cell_to_latlng(inner[idx])
        waypoints.append({"lat": round(lat, 6), "lon": round(lon, 6)})

    return waypoints


def _path_total_severity(hex_path: list[str], hex_grid: dict[str, float]) -> float:
    """Sum of severity along a hex path — used to compare alternatives."""
    return sum(_hex_severity(h, hex_grid) for h in hex_path)


# ─────────────────────────────────────────────────────────────────────────────
# DIRECT ROUTE SEVERITY CHECK
# ─────────────────────────────────────────────────────────────────────────────

def _straight_line_severity(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    hex_grid: dict[str, float],
    samples: int = 20,
) -> float:
    """Average severity along the straight line between two points."""
    total = 0.0
    for i in range(samples):
        t = i / max(samples - 1, 1)
        lat = lat1 + t * (lat2 - lat1)
        lon = lon1 + t * (lon2 - lon1)
        h = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
        total += _hex_severity(h, hex_grid)
    return total / samples


# ─────────────────────────────────────────────────────────────────────────────
# MAIN OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────

def optimize_route(
    scored_segments: list[ScoredSegment],
    grids_by_time: dict[float, dict[str, float]],
    flat_grid: dict[str, float],
    health_profile: str = "default",
    threshold: float = AVOIDANCE_THRESHOLD,
    max_iterations: int = MAX_ITERATIONS,
) -> dict:
    """
    Iteratively generate avoidance waypoints for high-risk route clusters.

    Each iteration:
      1. Find worst remaining risk cluster
      2. Resolve the time-appropriate hex grid for that cluster
      3. Dijkstra from cluster entry → exit through minimum-risk hexes
      4. Extract waypoints from the optimal hex path
      5. Record the waypoints (actual re-routing via Google Directions
         happens upstream — we output the waypoints for the caller)

    Args:
        scored_segments:  L3 output — segments with risk scores.
        grids_by_time:    L2 output — {hours: {hex: severity}} time-bucketed grids.
        flat_grid:        L2 output — peak severity per hex (used as fallback).
        health_profile:   For potential re-scoring.
        threshold:        Risk score that triggers avoidance.
        max_iterations:   Max clusters to fix per call.

    Returns:
        {
            "waypoints":          [{lat, lon}, ...] — ordered avoidance waypoints,
            "clusters_found":     int,
            "clusters_resolved":  int,
            "avoidance_details":  [{cluster, hex_path_len, waypoints, original_severity, new_severity}],
            "rerouted":           bool,
            "remaining_max_risk": float,
        }
    """
    logger.info(
        "optimize_route() — %d segments, threshold=%.2f, max_iter=%d",
        len(scored_segments), threshold, max_iterations,
    )

    all_waypoints: list[dict[str, float]] = []
    avoidance_details: list[dict] = []
    working_segments = list(scored_segments)

    for iteration in range(max_iterations):
        clusters = _find_risk_clusters(working_segments, threshold)
        if not clusters:
            logger.info("Iteration %d: no more risk clusters. Done.", iteration)
            break

        cluster = clusters[0]  # worst first
        logger.info(
            "Iteration %d: fixing cluster [%d→%d] peak=%.3f avg=%.3f (%d segs)",
            iteration, cluster.start_index, cluster.end_index,
            cluster.peak_risk, cluster.avg_risk, cluster.segment_count,
        )

        # Pick the time-appropriate grid for this cluster's location in the trip
        mid_seg_idx = (cluster.start_index + cluster.end_index) // 2
        mid_seg = next((s for s in working_segments if s.index == mid_seg_idx), working_segments[0])
        cum_hours = mid_seg.cumulative_time_min / 60.0

        # Find closest time bucket
        available = sorted(grids_by_time.keys()) if grids_by_time else [0]
        best_bucket = min(available, key=lambda h: abs(h - cum_hours))
        hex_grid = grids_by_time.get(best_bucket, flat_grid)

        # Entry/exit hexes
        start_hex = h3.latlng_to_cell(cluster.entry_lat, cluster.entry_lon, H3_RESOLUTION)
        goal_hex = h3.latlng_to_cell(cluster.exit_lat, cluster.exit_lon, H3_RESOLUTION)

        # Run Dijkstra
        hex_path = _dijkstra_hex_path(start_hex, goal_hex, hex_grid)

        if not hex_path:
            logger.warning("No avoidance path found for cluster [%d→%d], skipping.",
                           cluster.start_index, cluster.end_index)
            # Mark these segments so we don't retry them
            for seg in working_segments:
                if cluster.start_index <= seg.index <= cluster.end_index:
                    # Slightly reduce risk to prevent infinite loop
                    seg.risk_score = max(seg.risk_score * 0.95, 0.0)
            continue

        # Check if the Dijkstra path is actually better than the direct route
        original_sev = _path_total_severity(
            [h3.latlng_to_cell(
                s.start_lat, s.start_lon, H3_RESOLUTION
            ) for s in working_segments
             if cluster.start_index <= s.index <= cluster.end_index],
            hex_grid,
        )
        new_sev = _path_total_severity(hex_path, hex_grid)

        if new_sev >= original_sev * 0.9:
            logger.info(
                "Avoidance path not significantly better (%.2f vs %.2f), skipping.",
                new_sev, original_sev,
            )
            # Prevent re-processing
            for seg in working_segments:
                if cluster.start_index <= seg.index <= cluster.end_index:
                    seg.risk_score = max(seg.risk_score * 0.95, 0.0)
            continue

        # Check detour distance
        direct_km = _haversine_km(
            cluster.entry_lat, cluster.entry_lon,
            cluster.exit_lat, cluster.exit_lon,
        )
        detour_km = sum(
            _haversine_km(
                *h3.cell_to_latlng(hex_path[i]),
                *h3.cell_to_latlng(hex_path[i + 1]),
            )
            for i in range(len(hex_path) - 1)
        )

        if direct_km > 0 and detour_km / direct_km > MAX_DETOUR_FACTOR:
            logger.info(
                "Detour too long (%.1f km vs %.1f km direct, factor=%.1f), skipping.",
                detour_km, direct_km, detour_km / direct_km,
            )
            for seg in working_segments:
                if cluster.start_index <= seg.index <= cluster.end_index:
                    seg.risk_score = max(seg.risk_score * 0.95, 0.0)
            continue

        # Extract waypoints
        waypoints = _hex_path_to_waypoints(hex_path, max_waypoints=3)
        if not waypoints:
            logger.info("Hex path too short to extract waypoints, skipping.")
            continue

        all_waypoints.extend(waypoints)
        avoidance_details.append({
            "cluster_start": cluster.start_index,
            "cluster_end": cluster.end_index,
            "cluster_peak_risk": round(cluster.peak_risk, 4),
            "hex_path_length": len(hex_path),
            "waypoints": waypoints,
            "original_severity_sum": round(original_sev, 3),
            "new_severity_sum": round(new_sev, 3),
            "detour_km": round(detour_km, 2),
            "direct_km": round(direct_km, 2),
        })

        # Simulate improvement on working segments for next iteration
        # (real re-scoring happens after Google re-routes with waypoints)
        avoidance_hexes = set(hex_path)
        for seg in working_segments:
            if cluster.start_index <= seg.index <= cluster.end_index:
                seg_hex = h3.latlng_to_cell(
                    (seg.start_lat + seg.end_lat) / 2,
                    (seg.start_lon + seg.end_lon) / 2,
                    H3_RESOLUTION,
                )
                # Estimate new risk from the Dijkstra path's average severity
                seg.risk_score = new_sev / max(len(hex_path), 1)

        logger.info(
            "Cluster [%d→%d] resolved: %d waypoints, severity %.2f → %.2f",
            cluster.start_index, cluster.end_index,
            len(waypoints), original_sev, new_sev,
        )

    # Final risk check
    remaining_max = max((s.risk_score for s in working_segments), default=0.0)

    result = {
        "waypoints": all_waypoints,
        "clusters_found": len(_find_risk_clusters(scored_segments, threshold)),
        "clusters_resolved": len(avoidance_details),
        "avoidance_details": avoidance_details,
        "rerouted": len(all_waypoints) > 0,
        "remaining_max_risk": round(remaining_max, 4),
    }

    logger.info(
        "Optimization complete — %d waypoints across %d clusters, remaining_max=%.3f",
        len(all_waypoints), len(avoidance_details), remaining_max,
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE: FULL L1→L4 PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def optimize_scored_route(
    scored_segments: list[ScoredSegment],
    grids_by_time: dict[float, dict[str, float]],
    flat_grid: dict[str, float],
    origin: str,
    destination: str,
    health_profile: str = "default",
) -> OptimizedRoute:
    """
    High-level wrapper that runs the optimizer and returns an OptimizedRoute.

    This is what the router endpoint calls. It returns the schema the
    frontend expects, including waypoints for Google Directions re-query.
    """
    opt = optimize_route(
        scored_segments=scored_segments,
        grids_by_time=grids_by_time,
        flat_grid=flat_grid,
        health_profile=health_profile,
    )

    total_dist = sum(s.distance_km for s in scored_segments)
    total_time = (
        scored_segments[-1].cumulative_time_min + scored_segments[-1].travel_time_min
        if scored_segments else 0.0
    )

    # Build briefing text
    if opt["rerouted"]:
        n_wp = len(opt["waypoints"])
        n_cl = opt["clusters_resolved"]
        briefing = (
            f"Found {opt['clusters_found']} high-risk zone(s). "
            f"Generated {n_wp} avoidance waypoint(s) across {n_cl} zone(s). "
        )
        for detail in opt["avoidance_details"]:
            briefing += (
                f"Segments {detail['cluster_start']}–{detail['cluster_end']}: "
                f"detour {detail['detour_km']:.1f} km "
                f"(severity {detail['original_severity_sum']:.1f} → {detail['new_severity_sum']:.1f}). "
            )
    else:
        briefing = "Route is within acceptable risk levels. No rerouting needed."

    return OptimizedRoute(
        origin=origin,
        destination=destination,
        waypoints=opt["waypoints"],
        segments=scored_segments,
        max_risk_score=opt["remaining_max_risk"],
        total_distance_km=round(total_dist, 2),
        total_time_min=round(total_time, 2),
        rerouted=opt["rerouted"],
        briefing=briefing,
    )


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from models.schemas import HazardPoint, WindVector
    from services.hazard_field import generate_hazard_field
    from services.route_scorer import score_route
    from services.polyline_decoder import _haversine_km as hav

    # ── Mock data: fire blocking a route between two points ───────────────
    mock_fires = [
        HazardPoint(
            lat=51.12, lon=-115.80,
            hazard_type="wildfire", severity="high", source="NASA FIRMS",
            metadata={"frp_mw": 420.0, "confidence": "h"},
        ),
    ]
    mock_wind = [
        WindVector(lat=51.17, lon=-115.57, station_id="s1",
                   speed_kmh=28.0, direction_deg=270.0, gusts_kmh=42.0),
        WindVector(lat=51.08, lon=-115.35, station_id="s2",
                   speed_kmh=24.0, direction_deg=265.0, gusts_kmh=38.0),
        WindVector(lat=51.25, lon=-115.80, station_id="s3",
                   speed_kmh=31.0, direction_deg=275.0, gusts_kmh=45.0),
    ]
    mock_aqi = [
        HazardPoint(
            lat=51.20, lon=-115.60,
            hazard_type="smoke", severity="moderate", source="Open-Meteo AQ",
            spatial_impact_radius=15.0,
            metadata={"pm2_5_ugm3": 42.0, "us_aqi": 112},
        ),
    ]

    # Generate hazard field
    polygons, flat_grid, grids_by_time = generate_hazard_field(
        mock_fires, mock_wind, mock_aqi,
    )
    print(f"Hazard field: {len(flat_grid)} hexes, {len(grids_by_time)} time buckets")

    # Mock route: 20 segments through the fire zone
    mock_segments = []
    for i in range(20):
        mock_segments.append(RouteSegment(
            index=i,
            start_lat=51.05 + i * 0.02,
            start_lon=-116.20 + i * 0.04,
            end_lat=51.05 + (i + 1) * 0.02,
            end_lon=-116.20 + (i + 1) * 0.04,
            distance_km=10.0,
            travel_time_min=6.0,
            cumulative_time_min=i * 6.0,
        ))

    # Score the route
    result = score_route(mock_segments, grids_by_time)
    scored = result["scored_segments"]

    print(f"\nOriginal route: max_risk={result['max_risk_score']:.3f}, "
          f"level={result['route_risk_level']}")

    # Optimize
    opt = optimize_route(scored, grids_by_time, flat_grid)

    print(f"\n{'=' * 60}")
    print("OPTIMIZATION RESULT")
    print(f"{'=' * 60}")
    print(f"Clusters found:    {opt['clusters_found']}")
    print(f"Clusters resolved: {opt['clusters_resolved']}")
    print(f"Waypoints:         {len(opt['waypoints'])}")
    print(f"Rerouted:          {opt['rerouted']}")
    print(f"Remaining max:     {opt['remaining_max_risk']:.3f}")

    for i, wp in enumerate(opt["waypoints"]):
        print(f"  Waypoint {i+1}: ({wp['lat']:.6f}, {wp['lon']:.6f})")

    for detail in opt["avoidance_details"]:
        print(f"\n  Cluster [{detail['cluster_start']}→{detail['cluster_end']}]:")
        print(f"    Peak risk:     {detail['cluster_peak_risk']:.3f}")
        print(f"    Hex path:      {detail['hex_path_length']} hexes")
        print(f"    Severity:      {detail['original_severity_sum']:.2f} → {detail['new_severity_sum']:.2f}")
        print(f"    Detour:        {detail['detour_km']:.1f} km (direct {detail['direct_km']:.1f} km)")