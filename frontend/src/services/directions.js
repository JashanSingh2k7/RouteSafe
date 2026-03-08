const API_BASE = "";

export async function fetchRoute(origin, destination) {
  const params = new URLSearchParams({ origin, destination });
  const res = await fetch(`${API_BASE}/directions?${params}`);
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || `Directions request failed: ${res.status}`); }
  const data = await res.json();
  if (data.status && data.status !== "OK") throw new Error(`Google Directions: ${data.status}`);
  if (!data.routes || data.routes.length === 0) throw new Error("No routes found.");
  const route = data.routes[0], leg = route.legs[0];
  return { encodedPolyline: route.overview_polyline.points, totalDurationMin: leg.duration.value / 60, distanceKm: leg.distance.value / 1000, summary: route.summary, startAddress: leg.start_address, endAddress: leg.end_address };
}

export async function fetchRouteWithWaypoints(origin, destination, waypoints) {
  const params = new URLSearchParams({ origin, destination });
  if (waypoints?.length) params.set("waypoints", waypoints.map((wp) => `via:${wp.lat},${wp.lon}`).join("|"));
  const res = await fetch(`${API_BASE}/directions?${params}`);
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || `Directions request failed: ${res.status}`); }
  const data = await res.json();
  if (data.status && data.status !== "OK") throw new Error(`Google Directions: ${data.status}`);
  if (!data.routes || data.routes.length === 0) throw new Error("No route found with waypoints.");
  const route = data.routes[0];
  let totalDurationSec = 0, totalDistanceM = 0;
  for (const leg of route.legs) { totalDurationSec += leg.duration.value; totalDistanceM += leg.distance.value; }
  return { encodedPolyline: route.overview_polyline.points, totalDurationMin: totalDurationSec / 60, distanceKm: totalDistanceM / 1000, summary: route.summary, startAddress: route.legs[0].start_address, endAddress: route.legs[route.legs.length - 1].end_address };
}

export async function fetchAlternativeRoutes(origin, destination) {
  const params = new URLSearchParams({ origin, destination, alternatives: "true" });
  const res = await fetch(`${API_BASE}/directions?${params}`);
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || `Directions request failed: ${res.status}`); }
  const data = await res.json();
  if (data.status && data.status !== "OK") throw new Error(`Google Directions: ${data.status}`);
  if (!data.routes || data.routes.length === 0) throw new Error("No routes found.");
  return data.routes.map((route) => { const leg = route.legs[0]; return { encodedPolyline: route.overview_polyline.points, totalDurationMin: leg.duration.value / 60, distanceKm: leg.distance.value / 1000, summary: route.summary, startAddress: leg.start_address, endAddress: leg.end_address }; });
}