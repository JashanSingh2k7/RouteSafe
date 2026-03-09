"""
services/optimizer.py

L4 — Route Optimizer (v3)

Design principle: A LONGER CLEAN route is ALWAYS better than a shorter smoky one.

Key changes from v2:
  - Zero-tolerance smoke avoidance: any hex with severity > CLEAN_THRESHOLD
    gets exponential cost. The pathfinder treats smoke like a wall.
  - Adaptive blocked halo: scales with fire severity, not a fixed ring count.
  - Path validation: after Dijkstra finds a path, every hex is checked.
    If ANY waypoint lands in smoke, the waypoint is dropped.
  - Two-pass search: strict first, wider fallback.
  - More waypoints (up to 10) to accurately trace the clean corridor.
"""

import heapq
import logging
from dataclasses import dataclass, field
from typing import Optional

import h3

from models.schemas import ScoredSegment
from services.hazard_field import H3_RESOLUTION
from services.route_scorer import RISK_THRESHOLDS, _haversine_km

logger = logging.getLogger(__name__)


# ── CONFIGURATION ─────────────────────────────────────────────────────────────

AVOIDANCE_THRESHOLD: float = 0.20
CLEAN_THRESHOLD: float = 0.08      # hexes above this are "not clean"
CLUSTER_GAP_TOLERANCE: int = 3
SEARCH_RINGS: int = 25
MAX_ITERATIONS: int = 5
MAX_DETOUR_FACTOR: float = 4.0
ANCHOR_SEGMENT_BUFFER: int = 4

BASE_HEX_COST: float = 0.01
SMOKE_COST_MULTIPLIER: float = 20.0
SMOKE_WALL_COST: float = 5000.0

HALO_BASE_RINGS: int = 1
HALO_SEVERITY_SCALE: float = 3.0       # sev=0.8 -> 1+2=3 rings, sev=0.3 -> 1+0=1 ring

MAX_WAYPOINT_SEVERITY: float = 0.10      # allow waypoints near smoke edges
MAX_PATH_AVG_SEVERITY: float = 0.06


# ── DATA STRUCTURES ───────────────────────────────────────────────────────────

@dataclass
class RiskCluster:
    start_index: int
    end_index: int
    peak_risk: float
    avg_risk: float
    segment_count: int


@dataclass(order=True)
class _DijkstraNode:
    cost: float
    hex_id: str = field(compare=False)


# ── CLUSTER DETECTION ─────────────────────────────────────────────────────────

def _find_risk_clusters(segments, threshold=AVOIDANCE_THRESHOLD, gap_tolerance=CLUSTER_GAP_TOLERANCE):
    hot = [s.index for s in segments if s.risk_score >= threshold]
    if not hot:
        return []

    seg_map = {s.index: s for s in segments}
    groups, cur = [], [hot[0]]
    for idx in hot[1:]:
        if idx - cur[-1] <= gap_tolerance:
            cur.append(idx)
        else:
            groups.append(cur)
            cur = [idx]
    groups.append(cur)

    clusters = []
    for g in groups:
        segs = [seg_map[i] for i in g if i in seg_map]
        if not segs:
            continue
        risks = [s.risk_score for s in segs]
        clusters.append(RiskCluster(g[0], g[-1], max(risks), sum(risks)/len(risks), len(segs)))
    clusters.sort(key=lambda c: (c.peak_risk, c.segment_count), reverse=True)
    return clusters


# ── HEX HELPERS ───────────────────────────────────────────────────────────────

def _hex_sev(hx, grid):
    return float(grid.get(hx, 0.0))


def _seg_hexes(seg):
    hexes = {
        h3.latlng_to_cell(seg.start_lat, seg.start_lon, H3_RESOLUTION),
        h3.latlng_to_cell(seg.end_lat, seg.end_lon, H3_RESOLUTION),
    }
    mid_lat = (seg.start_lat + seg.end_lat) / 2
    mid_lon = (seg.start_lon + seg.end_lon) / 2
    hexes.add(h3.latlng_to_cell(mid_lat, mid_lon, H3_RESOLUTION))
    return hexes


def _pick_anchors(segments, cluster, buffer=ANCHOR_SEGMENT_BUFFER):
    seg_map = {s.index: s for s in segments}
    mn, mx = min(seg_map), max(seg_map)
    entry = seg_map.get(max(cluster.start_index - buffer, mn), seg_map[mn])
    exit_ = seg_map.get(min(cluster.end_index + buffer, mx), seg_map[mx])
    return (entry.start_lat, entry.start_lon), (exit_.end_lat, exit_.end_lon)


def _build_blocked(hex_grid, cluster_segs):
    blocked = set()
    # Block cluster hexes + adaptive halo
    for seg in cluster_segs:
        for hx in _seg_hexes(seg):
            blocked.add(hx)
            sev = max(_hex_sev(hx, hex_grid), seg.risk_score)
            halo = HALO_BASE_RINGS + int(sev * HALO_SEVERITY_SCALE)
            for nb in h3.grid_disk(hx, halo):
                blocked.add(nb)
    # Block all smoky hexes with adaptive halo
    for hx, sev in hex_grid.items():
        if sev >= CLEAN_THRESHOLD:
            blocked.add(hx)
            halo = HALO_BASE_RINGS + int(sev * HALO_SEVERITY_SCALE)
            for nb in h3.grid_disk(hx, halo):
                blocked.add(nb)
    return blocked


def _hex_cost(sev, is_blocked):
    if is_blocked:
        return SMOKE_WALL_COST
    if sev <= 0.0:
        return BASE_HEX_COST
    return BASE_HEX_COST + (sev ** 2) * SMOKE_COST_MULTIPLIER


# ── DIJKSTRA ──────────────────────────────────────────────────────────────────

def _dijkstra(start, goal, hex_grid, blocked, rings=SEARCH_RINGS):
    if start == goal:
        return [start]

    try:
        dd = h3.grid_distance(start, goal)
    except Exception:
        s, g = h3.cell_to_latlng(start), h3.cell_to_latlng(goal)
        dd = max(3, int(_haversine_km(s[0], s[1], g[0], g[1]) / 1.8))

    radius = min(max(rings, dd + 15), 70)
    ml = (h3.cell_to_latlng(start)[0] + h3.cell_to_latlng(goal)[0]) / 2
    mo = (h3.cell_to_latlng(start)[1] + h3.cell_to_latlng(goal)[1]) / 2
    mh = h3.latlng_to_cell(ml, mo, H3_RESOLUTION)

    allowed = set(h3.grid_disk(mh, radius))
    allowed.update(h3.grid_disk(start, 6))
    allowed.update(h3.grid_disk(goal, 6))

    safe_start = set(h3.grid_disk(start, 2))
    safe_goal = set(h3.grid_disk(goal, 2))
    eff_blocked = blocked - safe_start - safe_goal

    pq = [_DijkstraNode(0.0, start)]
    dist = {start: 0.0}
    parent = {start: None}
    visited = set()

    while pq:
        nd = heapq.heappop(pq)
        if nd.hex_id in visited:
            continue
        visited.add(nd.hex_id)

        if nd.hex_id == goal:
            path, cur = [], goal
            while cur is not None:
                path.append(cur)
                cur = parent[cur]
            path.reverse()
            return path

        for nb in h3.grid_disk(nd.hex_id, 1):
            if nb == nd.hex_id or nb in visited or nb not in allowed:
                continue
            sev = _hex_sev(nb, hex_grid)
            cost = nd.cost + _hex_cost(sev, nb in eff_blocked)
            if cost < dist.get(nb, float("inf")):
                dist[nb] = cost
                parent[nb] = nd.hex_id
                heapq.heappush(pq, _DijkstraNode(cost, nb))

    return None


# ── PATH VALIDATION ───────────────────────────────────────────────────────────

def _validate_path(path, grid):
    if not path:
        return False, 1.0, 1.0
    sevs = [_hex_sev(h, grid) for h in path]
    mx, avg = max(sevs), sum(sevs) / len(sevs)
    return mx <= MAX_WAYPOINT_SEVERITY and avg <= MAX_PATH_AVG_SEVERITY, mx, avg


# ── WAYPOINTS ─────────────────────────────────────────────────────────────────

def _dedupe(wps, gap=3.0):
    if not wps:
        return []
    out = [wps[0]]
    for wp in wps[1:]:
        if _haversine_km(out[-1]["lat"], out[-1]["lon"], wp["lat"], wp["lon"]) >= gap:
            out.append(wp)
    return out


def _path_to_waypoints(path, mx=20):
    """Sample waypoints at equal distance intervals along the hex path."""
    if len(path) < 4:
        return []
    inner = path[1:-1]
    if not inner:
        return []

    # Build cumulative distance along the inner path
    pts = [h3.cell_to_latlng(hx) for hx in inner]
    cum_dist = [0.0]
    for i in range(1, len(pts)):
        cum_dist.append(cum_dist[-1] + _haversine_km(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1]))

    total_dist = cum_dist[-1]
    if total_dist < 1.0:
        return []

    n = min(mx, max(4, len(inner) // 3))
    spacing = total_dist / (n + 1)

    wps = []
    next_target = spacing
    for i, d in enumerate(cum_dist):
        if d >= next_target:
            lat, lon = pts[i]
            wps.append({"lat": round(lat, 6), "lon": round(lon, 6)})
            next_target += spacing
            if len(wps) >= n:
                break

    return _dedupe(wps, 2.0)


# ── MAIN OPTIMIZER ────────────────────────────────────────────────────────────

def optimize_route(
    scored_segments, grids_by_time, flat_grid,
    health_profile="default", threshold=AVOIDANCE_THRESHOLD, max_iterations=MAX_ITERATIONS,
):
    logger.info("optimize_route() — %d segments, threshold=%.2f", len(scored_segments), threshold)

    if not scored_segments:
        return {"waypoints": [], "clusters_found": 0, "clusters_resolved": 0,
                "avoidance_details": [], "rerouted": False, "remaining_max_risk": 0.0}

    working = list(scored_segments)
    all_wps, details = [], []
    orig_clusters = _find_risk_clusters(working, threshold)

    for it in range(max_iterations):
        clusters = _find_risk_clusters(working, threshold)
        if not clusters:
            break

        cl = clusters[0]
        mid_idx = (cl.start_index + cl.end_index) // 2
        mid_seg = next((s for s in working if s.index == mid_idx), working[0])
        avail = sorted(grids_by_time.keys()) if grids_by_time else [0]
        bucket = min(avail, key=lambda h: abs(h - mid_seg.cumulative_time_min / 60.0))
        hex_grid = grids_by_time.get(bucket, flat_grid)

        entry, exit_ = _pick_anchors(working, cl)
        sh = h3.latlng_to_cell(entry[0], entry[1], H3_RESOLUTION)
        gh = h3.latlng_to_cell(exit_[0], exit_[1], H3_RESOLUTION)

        cl_segs = [s for s in working if cl.start_index <= s.index <= cl.end_index]
        blocked = _build_blocked(hex_grid, cl_segs)

        # Pass 1: strict
        path = _dijkstra(sh, gh, hex_grid, blocked)
        if path:
            ok, mx, avg = _validate_path(path, hex_grid)
            if not ok:
                # Pass 2: wider search
                path = _dijkstra(sh, gh, hex_grid, blocked, rings=SEARCH_RINGS + 20)
                if path:
                    ok, mx, avg = _validate_path(path, hex_grid)

        if not path:
            for s in working:
                if cl.start_index <= s.index <= cl.end_index:
                    s.risk_score *= 0.97
            continue

        # Compute severity improvement
        orig_hexes = []
        for s in working:
            if cl.start_index <= s.index <= cl.end_index:
                orig_hexes.extend(list(_seg_hexes(s)))
        orig_sev = sum(_hex_sev(h, hex_grid) for h in orig_hexes)
        new_sev = sum(_hex_sev(h, hex_grid) for h in path)

        direct_km = _haversine_km(entry[0], entry[1], exit_[0], exit_[1])
        detour_km = sum(
            _haversine_km(*h3.cell_to_latlng(path[i]), *h3.cell_to_latlng(path[i+1]))
            for i in range(len(path)-1)
        )

        if direct_km > 0 and detour_km / direct_km > MAX_DETOUR_FACTOR:
            for s in working:
                if cl.start_index <= s.index <= cl.end_index:
                    s.risk_score *= 0.97
            continue

        improvement = 1.0 - (new_sev / max(orig_sev, 0.001))
        if improvement < 0.30:
            for s in working:
                if cl.start_index <= s.index <= cl.end_index:
                    s.risk_score *= 0.97
            continue

        wps = _path_to_waypoints(path, mx=20)
        if not wps:
            continue

        # Final filter: check flat_grid (worst-case) + neighbors
        # Google snaps routes to roads which may be 1 hex over
        clean_wps = []
        for wp in wps:
            wp_hex = h3.latlng_to_cell(wp["lat"], wp["lon"], H3_RESOLUTION)
            wp_sev = _hex_sev(wp_hex, flat_grid)
            neighbor_max = max(_hex_sev(n, flat_grid) for n in h3.grid_disk(wp_hex, 1))
            if neighbor_max <= MAX_WAYPOINT_SEVERITY:
                clean_wps.append(wp)

        if not clean_wps:
            for s in working:
                if cl.start_index <= s.index <= cl.end_index:
                    s.risk_score *= 0.97
            continue

        all_wps.extend(clean_wps)
        details.append({
            "cluster_start": cl.start_index, "cluster_end": cl.end_index,
            "cluster_peak_risk": round(cl.peak_risk, 4),
            "hex_path_length": len(path), "waypoints": clean_wps,
            "original_severity_sum": round(orig_sev, 3),
            "new_severity_sum": round(new_sev, 3),
            "detour_km": round(detour_km, 2), "direct_km": round(direct_km, 2),
            "improvement_pct": round(improvement * 100, 1),
        })

        for s in working:
            if cl.start_index <= s.index <= cl.end_index:
                s.risk_score = min(s.risk_score, max(0.02, cl.avg_risk * 0.15))

    remaining_max = max((s.risk_score for s in working), default=0.0)
    all_wps = _dedupe(all_wps, 2.0)

    return {
        "waypoints": all_wps,
        "clusters_found": len(orig_clusters),
        "clusters_resolved": len(details),
        "avoidance_details": details,
        "rerouted": len(all_wps) > 0,
        "remaining_max_risk": round(remaining_max, 4),
    }