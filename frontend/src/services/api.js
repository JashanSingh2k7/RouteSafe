/**
 * services/api.js
 *
 * All backend API calls in one place.
 * Vite proxy forwards /score/*, /ingest/*, /optimize/* to localhost:8000.
 *
 * Every function here maps directly to an endpoint in the FastAPI backend.
 */

const API_BASE = "";

// ─────────────────────────────────────────────────────────────────────────────
// POST /score/route — full L1 → L2 → L3 pipeline
// ─────────────────────────────────────────────────────────────────────────────

let scoreAbort = null;

export async function scoreRoute({
  encodedPolyline,
  totalDurationMin,
  radiusKm = 100,
  dayRange = 1,
  windSampleEvery = 5,
  aqiSampleEvery = 5,
  healthProfile = "default",
}) {
  // Cancel any in-flight scoring request
  if (scoreAbort) scoreAbort.abort();
  scoreAbort = new AbortController();

  const res = await fetch(`${API_BASE}/score/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: scoreAbort.signal,
    body: JSON.stringify({
      encoded_polyline: encodedPolyline,
      total_duration_min: totalDurationMin,
      radius_km: radiusKm,
      day_range: dayRange,
      wind_sample_every: windSampleEvery,
      aqi_sample_every: aqiSampleEvery,
      health_profile: healthProfile,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Scoring failed with status ${res.status}`);
  }

  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// POST /optimize/route — full L1 → L2 → L3 → L4 pipeline
// ─────────────────────────────────────────────────────────────────────────────

let optimizeAbort = null;

export async function optimizeRoute({
  encodedPolyline,
  totalDurationMin,
  origin,
  destination,
  radiusKm = 100,
  dayRange = 1,
  windSampleEvery = 5,
  aqiSampleEvery = 5,
  healthProfile = "default",
  riskThreshold = 0.40,
}) {
  if (optimizeAbort) optimizeAbort.abort();
  optimizeAbort = new AbortController();

  const res = await fetch(`${API_BASE}/optimize/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: optimizeAbort.signal,
    body: JSON.stringify({
      encoded_polyline: encodedPolyline,
      total_duration_min: totalDurationMin,
      origin,
      destination,
      radius_km: radiusKm,
      day_range: dayRange,
      wind_sample_every: windSampleEvery,
      aqi_sample_every: aqiSampleEvery,
      health_profile: healthProfile,
      risk_threshold: riskThreshold,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Optimization failed with status ${res.status}`);
  }

  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// GET /score/profiles — health profile list for the dropdown
// ─────────────────────────────────────────────────────────────────────────────

export async function getProfiles() {
  const res = await fetch(`${API_BASE}/score/profiles`);

  if (!res.ok) {
    throw new Error(`Failed to fetch profiles: ${res.status}`);
  }

  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// GET /health — backend liveness check
// ─────────────────────────────────────────────────────────────────────────────

export async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}