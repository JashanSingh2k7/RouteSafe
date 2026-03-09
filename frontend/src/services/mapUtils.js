/**
 * services/mapUtils.js — GeoJSON builders + bounds utilities
 */

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

export function segmentsToGeoJSON(segments) {
  return {
    type: "FeatureCollection",
    features: segments.map((seg) => ({
      type: "Feature",
      properties: {
        index: seg.index, risk_score: seg.risk_score, hazard_type: seg.hazard_type,
        aqi_estimate: seg.aqi_estimate, distance_km: seg.distance_km,
        travel_time_min: seg.travel_time_min, cumulative_time_min: seg.cumulative_time_min,
      },
      geometry: { type: "LineString", coordinates: [[seg.start_lon, seg.start_lat], [seg.end_lon, seg.end_lat]] },
    })),
  };
}

export function polygonsToGeoJSON(polygons, selectedHours = null) {
  let filtered = polygons;
  if (selectedHours !== null && selectedHours !== undefined && polygons.length > 0) {
    const times = polygons.map((p) => new Date(p.valid_at).getTime());
    const earliest = Math.min(...times);
    filtered = polygons.filter((poly) => {
      const hoursFromStart = (new Date(poly.valid_at).getTime() - earliest) / (1000 * 60 * 60);
      return hoursFromStart <= selectedHours + 0.1;
    });
  }
  return {
    type: "FeatureCollection",
    features: filtered.map((poly) => ({
      type: "Feature",
      properties: { severity: poly.severity, hazard_type: poly.hazard_type, valid_at: poly.valid_at, source_fire: poly.source_fire, opacity: plumeSeverityOpacity(poly.severity) },
      geometry: { type: "Polygon", coordinates: [poly.coordinates] },
    })),
  };
}

export function firesToGeoJSON(fires) {
  return {
    type: "FeatureCollection",
    features: fires.map((fire) => ({
      type: "Feature",
      properties: { severity: fire.severity, frp_mw: fire.metadata?.frp_mw || null, source: fire.source || "NASA FIRMS" },
      geometry: { type: "Point", coordinates: [fire.lon, fire.lat] },
    })),
  };
}

export async function hexGridToGeoJSON(hexGrid) {
  const h3 = await import("h3-js");
  const features = [];
  for (const [hexId, severity] of Object.entries(hexGrid)) {
    try {
      const boundary = h3.cellToBoundary(hexId).map(([lat, lng]) => [lng, lat]);
      boundary.push(boundary[0]);
      features.push({ type: "Feature", properties: { h3_index: hexId, severity }, geometry: { type: "Polygon", coordinates: [boundary] } });
    } catch (e) {}
  }
  return { type: "FeatureCollection", features };
}

export function getRouteBounds(segments) {
  let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity;
  for (const seg of segments) {
    minLat = Math.min(minLat, seg.start_lat, seg.end_lat);
    maxLat = Math.max(maxLat, seg.start_lat, seg.end_lat);
    minLon = Math.min(minLon, seg.start_lon, seg.end_lon);
    maxLon = Math.max(maxLon, seg.start_lon, seg.end_lon);
  }
  const latPad = (maxLat - minLat) * 0.05 + 0.02;
  const lonPad = (maxLon - minLon) * 0.05 + 0.02;
  return [[minLon - lonPad, minLat - latPad], [maxLon + lonPad, maxLat + latPad]];
}

export function getFullBounds(segments, fires, waypoints) {
  let minLat = Infinity, maxLat = -Infinity;
  let minLon = Infinity, maxLon = -Infinity;

  const extend = (lat, lon) => {
    minLat = Math.min(minLat, lat);
    maxLat = Math.max(maxLat, lat);
    minLon = Math.min(minLon, lon);
    maxLon = Math.max(maxLon, lon);
  };

  for (const seg of (segments || [])) {
    extend(seg.start_lat, seg.start_lon);
    extend(seg.end_lat, seg.end_lon);
  }
  for (const fire of (fires || [])) {
    extend(fire.lat, fire.lon);
  }
  for (const wp of (waypoints || [])) {
    extend(wp.lat, wp.lon);
  }

  if (minLat === Infinity) return null;

  const latPad = (maxLat - minLat) * 0.05 + 0.02;
  const lonPad = (maxLon - minLon) * 0.05 + 0.02;

  return [
    [minLon - lonPad, minLat - latPad],
    [maxLon + lonPad, maxLat + latPad],
  ];
}
