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

/**
 * Risk score (0–1) → color string.
 * Gray for safe/moderate, orange for dangerous, red for critical.
 */
export function riskColor(score) {
  if (score < 0.15) return "#555555";
  if (score < 0.35) return "#777777";
  if (score < 0.6) return "#f97316";
  return "#ef4444";
}

/**
 * Risk score → human label. Thresholds match route_scorer.py RISK_THRESHOLDS.
 */
export function riskLabel(score) {
  if (score < 0.15) return "safe";
  if (score < 0.4) return "moderate";
  if (score < 0.7) return "dangerous";
  return "critical";
}

/**
 * Plume severity string → fill opacity.
 * More severe plumes render more opaque on the map.
 */
export function plumeSeverityOpacity(severity) {
  const map = { low: 0.04, moderate: 0.08, high: 0.12, critical: 0.18 };
  return map[severity] || 0.06;
}

// ─────────────────────────────────────────────────────────────────────────────
// GEOJSON BUILDERS — backend data → Mapbox sources
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Convert scored_segments array into a GeoJSON FeatureCollection.
 * Each segment becomes a LineString with risk properties attached.
 *
 * Properties are passed through so Mapbox can use them in
 * data-driven styling (e.g. color by risk_score) and popups.
 *
 * Backend fields: index, start_lat, start_lon, end_lat, end_lon,
 *   risk_score, hazard_type, aqi_estimate, distance_km,
 *   travel_time_min, cumulative_time_min
 */
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

/**
 * Build a single LineString of the full route path.
 * Useful for drawing a route outline underneath the per-segment coloring.
 */
export function routeToLineGeoJSON(segments) {
  if (!segments.length) return { type: "FeatureCollection", features: [] };

  const coords = segments.map((seg) => [seg.start_lon, seg.start_lat]);
  // Add the final segment's endpoint
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

/**
 * Convert hazard_polygons array into a GeoJSON FeatureCollection.
 * Each polygon is a smoke plume with severity and timestamp.
 *
 * If selectedHours is provided, only includes polygons whose valid_at
 * falls within that time horizon (matching L2's TIME_HORIZONS_HOURS).
 * If null/undefined, returns all polygons.
 *
 * Backend fields: hazard_type, severity, valid_at, coordinates, source_fire
 *
 * coordinates come as [[lon, lat], ...] from the backend (GeoJSON order),
 * so they can be used directly — no flipping needed.
 */
export function polygonsToGeoJSON(polygons, selectedHours = null) {
  let filtered = polygons;

  if (selectedHours !== null && selectedHours !== undefined) {
    // Each polygon has a valid_at timestamp. Filter to only show
    // polygons at or before the selected time horizon.
    // We compare hours offset from the earliest valid_at in the set.
    if (polygons.length > 0) {
      const times = polygons.map((p) => new Date(p.valid_at).getTime());
      const earliest = Math.min(...times);

      filtered = polygons.filter((poly) => {
        const hoursFromStart = (new Date(poly.valid_at).getTime() - earliest) / (1000 * 60 * 60);
        return hoursFromStart <= selectedHours + 0.1; // small tolerance
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

/**
 * Convert fire hazard data into a GeoJSON FeatureCollection of Points.
 * Used for fire marker dots on the map.
 *
 * Accepts the fire_hazards from the backend or extracted fire locations.
 * Each fire needs at minimum: lat, lon, severity
 */
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
// MAP BOUNDS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Compute the bounding box of all segments for map.fitBounds().
 * Returns [[minLon, minLat], [maxLon, maxLat]] with padding.
 */
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

  // Pad by 5% of the range for breathing room
  const latPad = (maxLat - minLat) * 0.05 + 0.02;
  const lonPad = (maxLon - minLon) * 0.05 + 0.02;

  return [
    [minLon - lonPad, minLat - latPad],
    [maxLon + lonPad, maxLat + latPad],
  ];
}