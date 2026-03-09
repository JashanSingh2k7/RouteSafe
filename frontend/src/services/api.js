const API_BASE = "";

let scoreAbort = null;
export async function scoreRoute({ encodedPolyline, totalDurationMin, radiusKm = 100, dayRange = 1, windSampleEvery = 5, aqiSampleEvery = 5, healthProfile = "default" }) {
  if (scoreAbort) scoreAbort.abort();
  scoreAbort = new AbortController();
  const res = await fetch(`${API_BASE}/score/route`, {
    method: "POST", headers: { "Content-Type": "application/json" }, signal: scoreAbort.signal,
    body: JSON.stringify({ encoded_polyline: encodedPolyline, total_duration_min: totalDurationMin, radius_km: radiusKm, day_range: dayRange, wind_sample_every: windSampleEvery, aqi_sample_every: aqiSampleEvery, health_profile: healthProfile }),
  });
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || `Scoring failed: ${res.status}`); }
  return res.json();
}

let optimizeAbort = null;
export async function optimizeRoute({ encodedPolyline, totalDurationMin, origin, destination, radiusKm = 100, dayRange = 1, windSampleEvery = 5, aqiSampleEvery = 5, healthProfile = "default", riskThreshold = 0.40 }) {
  if (optimizeAbort) optimizeAbort.abort();
  optimizeAbort = new AbortController();
  const res = await fetch(`${API_BASE}/optimize/route`, {
    method: "POST", headers: { "Content-Type": "application/json" }, signal: optimizeAbort.signal,
    body: JSON.stringify({ encoded_polyline: encodedPolyline, total_duration_min: totalDurationMin, origin, destination, radius_km: radiusKm, day_range: dayRange, wind_sample_every: windSampleEvery, aqi_sample_every: aqiSampleEvery, health_profile: healthProfile, risk_threshold: riskThreshold }),
  });
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || `Optimization failed: ${res.status}`); }
  return res.json();
}

export async function getProfiles() {
  const res = await fetch(`${API_BASE}/score/profiles`);
  if (!res.ok) throw new Error(`Failed to fetch profiles: ${res.status}`);
  return res.json();
}

export async function checkHealth() {
  try { const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) }); return res.ok; } catch { return false; }
}