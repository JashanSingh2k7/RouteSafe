/**
 * services/directions.js
 *
 * Gets encoded polylines from Google Directions API.
 *
 * Google Directions REST API doesn't allow browser CORS requests,
 * so we proxy through our FastAPI backend:
 *   Frontend → Vite proxy → FastAPI /directions → Google → back
 *
 * The backend endpoint needs to be added to your FastAPI app.
 * See directions_proxy.py in the backend for the implementation.
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
 *     encodedPolyline:  string,    // Google's encoded polyline
 *     totalDurationMin: number,    // trip time in minutes
 *     distanceKm:       number,    // trip distance in km
 *     summary:          string,    // route name e.g. "Trans-Canada Hwy"
 *     startAddress:     string,    // resolved origin address
 *     endAddress:       string,    // resolved destination address
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

  // Google returns { routes: [...], status: "OK" | "ZERO_RESULTS" | ... }
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
 * Fetch multiple alternative routes between two locations.
 * Useful for L4 route optimization — compare risk across alternatives.
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