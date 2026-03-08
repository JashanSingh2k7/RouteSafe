/**
 * services/directions.js
 *
 * Gets encoded polylines from Google Directions API.
 *
 * Google Directions REST API doesn't allow browser CORS requests,
 * so we proxy through our FastAPI backend:
 *   Frontend → Vite proxy → FastAPI /directions → Google → back
 *
 * Returns the encoded polyline + duration that scoreRoute() expects.
 */

const API_BASE = "";

/**
 * Fetch a driving route between two locations.
 *
 * @param {string} origin      — e.g. "Calgary, AB"
 * @param {string} destination — e.g. "Banff, AB"
 * @returns {object} Route data shaped for scoreRoute():
 *   {
 *     encodedPolyline:  string,
 *     totalDurationMin: number,
 *     distanceKm:       number,
 *     summary:          string,
 *     startAddress:     string,
 *     endAddress:       string,
 *   }
 */
export async function fetchRoute(origin, destination) {
  const params = new URLSearchParams({
    origin: origin,
    destination: destination,
  });

  const res = await fetch(`${API_BASE}/directions?${params}`);

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Directions request failed: ${res.status}`);
  }

  const data = await res.json();

  if (data.status && data.status !== "OK") {
    throw new Error(`Google Directions: ${data.status}`);
  }

  if (!data.routes || data.routes.length === 0) {
    throw new Error("No routes found between those locations.");
  }

  const route = data.routes[0];
  const leg = route.legs[0];

  return {
    encodedPolyline: route.overview_polyline.points,
    totalDurationMin: leg.duration.value / 60,
    distanceKm: leg.distance.value / 1000,
    summary: route.summary,
    startAddress: leg.start_address,
    endAddress: leg.end_address,
  };
}

/**
 * Fetch a route with avoidance waypoints from L4 optimizer.
 *
 * Google Directions accepts waypoints as pipe-separated "via:" locations.
 * These are pass-through waypoints (the route bends toward them
 * without actually stopping).
 *
 * @param {string} origin
 * @param {string} destination
 * @param {Array}  waypoints — [{lat, lon}, ...] from optimizer
 * @returns {object} Same shape as fetchRoute()
 */
export async function fetchRouteWithWaypoints(origin, destination, waypoints) {
  const params = new URLSearchParams({
    origin,
    destination,
  });

  // Format waypoints as "via:lat,lon|via:lat,lon"
  // "via:" tells Google to route through without stopping
  if (waypoints?.length) {
    const wpStr = waypoints
      .map((wp) => `via:${wp.lat},${wp.lon}`)
      .join("|");
    params.set("waypoints", wpStr);
  }

  const res = await fetch(`${API_BASE}/directions?${params}`);

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Directions request failed: ${res.status}`);
  }

  const data = await res.json();

  if (data.status && data.status !== "OK") {
    throw new Error(`Google Directions: ${data.status}`);
  }

  if (!data.routes || data.routes.length === 0) {
    throw new Error("No route found with avoidance waypoints.");
  }

  const route = data.routes[0];

  // With waypoints, Google splits the route into multiple legs
  // Sum up all legs for total duration and distance
  let totalDurationSec = 0;
  let totalDistanceM = 0;
  for (const leg of route.legs) {
    totalDurationSec += leg.duration.value;
    totalDistanceM += leg.distance.value;
  }

  return {
    encodedPolyline: route.overview_polyline.points,
    totalDurationMin: totalDurationSec / 60,
    distanceKm: totalDistanceM / 1000,
    summary: route.summary,
    startAddress: route.legs[0].start_address,
    endAddress: route.legs[route.legs.length - 1].end_address,
  };
}

/**
 * Fetch multiple alternative routes between two locations.
 * Useful for comparing risk across alternatives.
 *
 * @returns {Array} Array of route objects, same shape as fetchRoute().
 */
export async function fetchAlternativeRoutes(origin, destination) {
  const params = new URLSearchParams({
    origin: origin,
    destination: destination,
    alternatives: "true",
  });

  const res = await fetch(`${API_BASE}/directions?${params}`);

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Directions request failed: ${res.status}`);
  }

  const data = await res.json();

  if (data.status && data.status !== "OK") {
    throw new Error(`Google Directions: ${data.status}`);
  }

  if (!data.routes || data.routes.length === 0) {
    throw new Error("No routes found between those locations.");
  }

  return data.routes.map((route) => {
    const leg = route.legs[0];
    return {
      encodedPolyline: route.overview_polyline.points,
      totalDurationMin: leg.duration.value / 60,
      distanceKm: leg.distance.value / 1000,
      summary: route.summary,
      startAddress: leg.start_address,
      endAddress: leg.end_address,
    };
  });
}