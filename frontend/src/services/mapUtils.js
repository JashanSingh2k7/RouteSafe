/**
 * services/mapUtils.js
 *
 * Pure utility functions for converting backend response data into
 * Mapbox GL compatible formats. No side effects, no API calls.
 *
 * Used by: components/Map.jsx, components/SidePanel.jsx
 *
 * All property names match the backend's ScoreRouteResponse schema
 * (snake_case from FastAPI).
 */

// ─────────────────────────────────────────────────────────────────────────────
// RISK STYLING — monochrome base, orange/red for danger
// ─────────────────────────────────────────────────────────────────────────────

export function riskColor(score) {
  if (score < 0.15) return "#555555";
  if (score < 0.35) return "#777777";
  if (score < 0.6) return "#f97316";
  return "#ef4444";
}

export function riskLabel(score) {
  if (score < 0.15) return "safe";
  if (score < 0.4) return "moderate";
  if (score < 0.7) return "dangerous";
  return "critical";
}

export function plumeSeverityOpacity(severity) {
  const map = { low: 0.04, moderate: 0.08, high: 0.12, critical: 0.18 };
  return map[severity] || 0.06;
}

// ─────────────────────────────────────────────────────────────────────────────
// GEOJSON BUILDERS
// ─────────────────────────────────────────────────────────────────────────────

export function segmentsToGeoJSON(segments) {
  return {
    type: "FeatureCollection",
    features: segments.map((seg) => ({
      type: "Feature",
      properties: {
        index: seg.index,
        risk_score: seg.risk_score,
        hazard_type: seg.hazard_type,
        aqi_estimate: seg.aqi_estimate,
        distance_km: seg.distance_km,
        travel_time_min: seg.travel_time_min,
        cumulative_time_min: seg.cumulative_time_min,
      },
      geometry: {
        type: "LineString",
        coordinates: [
          [seg.start_lon, seg.start_lat],
          [seg.end_lon, seg.end_lat],
        ],
      },
    })),
  };
}

export function routeToLineGeoJSON(segments) {
  if (!segments.length) return { type: "FeatureCollection", features: [] };
  const coords = segments.map((seg) => [seg.start_lon, seg.start_lat]);
  const last = segments[segments.length - 1];
  coords.push([last.end_lon, last.end_lat]);
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: { type: "LineString", coordinates: coords },
      },
    ],
  };
}

export function polygonsToGeoJSON(polygons, selectedHours = null) {
  let filtered = polygons;

  if (selectedHours !== null && selectedHours !== undefined) {
    if (polygons.length > 0) {
      const times = polygons.map((p) => new Date(p.valid_at).getTime());
      const earliest = Math.min(...times);
      filtered = polygons.filter((poly) => {
        const hoursFromStart =
          (new Date(poly.valid_at).getTime() - earliest) / (1000 * 60 * 60);
        return hoursFromStart <= selectedHours + 0.1;
      });
    }
  }

  return {
    type: "FeatureCollection",
    features: filtered.map((poly) => ({
      type: "Feature",
      properties: {
        severity: poly.severity,
        hazard_type: poly.hazard_type,
        valid_at: poly.valid_at,
        source_fire: poly.source_fire,
        opacity: plumeSeverityOpacity(poly.severity),
      },
      geometry: {
        type: "Polygon",
        coordinates: [poly.coordinates],
      },
    })),
  };
}

export function firesToGeoJSON(fires) {
  return {
    type: "FeatureCollection",
    features: fires.map((fire) => ({
      type: "Feature",
      properties: {
        severity: fire.severity,
        frp_mw: fire.metadata?.frp_mw || null,
        source: fire.source || "NASA FIRMS",
      },
      geometry: {
        type: "Point",
        coordinates: [fire.lon, fire.lat],
      },
    })),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// H3 HEX GRID
// ─────────────────────────────────────────────────────────────────────────────

export async function hexGridToGeoJSON(hexGrid) {
  const h3 = await import("h3-js");

  const features = [];

  for (const [hexId, severity] of Object.entries(hexGrid)) {
    try {
      const boundary = h3.cellToBoundary(hexId).map(([lat, lng]) => [lng, lat]);
      boundary.push(boundary[0]);

      features.push({
        type: "Feature",
        properties: {
          h3_index: hexId,
          severity: severity,
        },
        geometry: {
          type: "Polygon",
          coordinates: [boundary],
        },
      });
    } catch (e) {
      // Skip invalid hex IDs
    }
  }

  return { type: "FeatureCollection", features };
}

// ─────────────────────────────────────────────────────────────────────────────
// MAP BOUNDS
// ─────────────────────────────────────────────────────────────────────────────

export function getRouteBounds(segments) {
  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLon = Infinity;
  let maxLon = -Infinity;

  for (const seg of segments) {
    minLat = Math.min(minLat, seg.start_lat, seg.end_lat);
    maxLat = Math.max(maxLat, seg.start_lat, seg.end_lat);
    minLon = Math.min(minLon, seg.start_lon, seg.end_lon);
    maxLon = Math.max(maxLon, seg.start_lon, seg.end_lon);
  }

  const latPad = (maxLat - minLat) * 0.05 + 0.02;
  const lonPad = (maxLon - minLon) * 0.05 + 0.02;

  return [
    [minLon - lonPad, minLat - latPad],
    [maxLon + lonPad, maxLat + latPad],
  ];
}

/**
 * Compute bounds that include the route, fires, and avoidance waypoints.
 * This ensures the user can see the full picture — not just the route.
 */
export function getFullBounds(segments, fires, waypoints) {
  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLon = Infinity;
  let maxLon = -Infinity;

  // Include route segments
  if (segments?.length) {
    for (const seg of segments) {
      minLat = Math.min(minLat, seg.start_lat, seg.end_lat);
      maxLat = Math.max(maxLat, seg.start_lat, seg.end_lat);
      minLon = Math.min(minLon, seg.start_lon, seg.end_lon);
      maxLon = Math.max(maxLon, seg.start_lon, seg.end_lon);
    }
  }

  // Include fire locations
  if (fires?.length) {
    for (const fire of fires) {
      minLat = Math.min(minLat, fire.lat);
      maxLat = Math.max(maxLat, fire.lat);
      minLon = Math.min(minLon, fire.lon);
      maxLon = Math.max(maxLon, fire.lon);
    }
  }

  // Include waypoints
  if (waypoints?.length) {
    for (const wp of waypoints) {
      minLat = Math.min(minLat, wp.lat);
      maxLat = Math.max(maxLat, wp.lat);
      minLon = Math.min(minLon, wp.lon);
      maxLon = Math.max(maxLon, wp.lon);
    }
  }

  if (minLat === Infinity) return null;

  const latPad = (maxLat - minLat) * 0.08 + 0.02;
  const lonPad = (maxLon - minLon) * 0.08 + 0.02;

  return [
    [minLon - lonPad, minLat - latPad],
    [maxLon + lonPad, maxLat + latPad],
  ];
}