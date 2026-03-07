// src/components/RouteInput.jsx
// Input form: two modes — "route" (origin/destination) and "polyline" (paste encoded string).
// Also has the health profile dropdown and submit button.

import { useState, useEffect } from "react";
import { getProfiles } from "../services/api";

export default function RouteInput({ onSubmit, loading }) {
  const [mode, setMode] = useState("polyline"); // "route" | "polyline"
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [polyline, setPolyline] = useState("");
  const [durationMin, setDurationMin] = useState(120);
  const [radiusKm, setRadiusKm] = useState(100);
  const [dayRange, setDayRange] = useState(1);
  const [profile, setProfile] = useState("default");
  const [profiles, setProfiles] = useState([]);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    getProfiles()
      .then(setProfiles)
      .catch(() => {
        // Fallback profiles if backend is unreachable
        setProfiles([
          { key: "default", label: "Healthy adult (driving)", breathing_rate: 1.0, sensitivity: 1.0 },
          { key: "child", label: "Child (under 12)", breathing_rate: 0.35, sensitivity: 1.6 },
          { key: "asthma", label: "Asthma / respiratory condition", breathing_rate: 1.0, sensitivity: 2.0 },
          { key: "elderly", label: "Elderly (65+)", breathing_rate: 0.45, sensitivity: 1.4 },
          { key: "pregnant", label: "Pregnant", breathing_rate: 1.15, sensitivity: 1.3 },
          { key: "outdoor_worker", label: "Outdoor / truck worker", breathing_rate: 1.8, sensitivity: 1.0 },
        ]);
      });
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();

    if (mode === "polyline") {
      if (!polyline.trim()) return;
      onSubmit({
        encoded_polyline: polyline.trim(),
        total_duration_min: parseFloat(durationMin) || 120,
        radius_km: radiusKm,
        day_range: dayRange,
        health_profile: profile,
      });
    } else {
      // Route mode — the backend would need a Google Directions proxy
      // For now, this is a placeholder that shows intent
      if (!origin.trim() || !destination.trim()) return;
      onSubmit({
        mode: "route",
        origin: origin.trim(),
        destination: destination.trim(),
        health_profile: profile,
        radius_km: radiusKm,
        day_range: dayRange,
      });
    }
  };

  const selectedProfile = profiles.find((p) => p.key === profile);

  return (
    <form onSubmit={handleSubmit} className="route-input">
      {/* ── Mode Toggle ──────────────────────────────────────────── */}
      <div className="input-mode-toggle">
        <button
          type="button"
          className={`mode-btn ${mode === "route" ? "active" : ""}`}
          onClick={() => setMode("route")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/>
            <circle cx="12" cy="9" r="2.5"/>
          </svg>
          Route
        </button>
        <button
          type="button"
          className={`mode-btn ${mode === "polyline" ? "active" : ""}`}
          onClick={() => setMode("polyline")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="4 17 10 11 4 5"/>
            <line x1="12" y1="19" x2="20" y2="19"/>
          </svg>
          Polyline
        </button>
      </div>

      {/* ── Route Mode ───────────────────────────────────────────── */}
      {mode === "route" && (
        <div className="input-fields">
          <div className="input-group">
            <label>Origin</label>
            <input
              type="text"
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              placeholder="Calgary, AB"
              disabled={loading}
            />
          </div>
          <div className="input-group">
            <label>Destination</label>
            <input
              type="text"
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              placeholder="Kamloops, BC"
              disabled={loading}
            />
          </div>
        </div>
      )}

      {/* ── Polyline Mode ────────────────────────────────────────── */}
      {mode === "polyline" && (
        <div className="input-fields">
          <div className="input-group">
            <label>Encoded Polyline</label>
            <textarea
              value={polyline}
              onChange={(e) => setPolyline(e.target.value)}
              placeholder="Paste a Google Directions encoded polyline..."
              rows={3}
              disabled={loading}
              spellCheck={false}
              style={{ fontFamily: "monospace", fontSize: "11px" }}
            />
          </div>
          <div className="input-group">
            <label>Trip Duration (min)</label>
            <input
              type="number"
              value={durationMin}
              onChange={(e) => setDurationMin(e.target.value)}
              min={1}
              max={2880}
              disabled={loading}
            />
          </div>
        </div>
      )}

      {/* ── Health Profile ───────────────────────────────────────── */}
      <div className="input-group">
        <label>Health Profile</label>
        <select
          value={profile}
          onChange={(e) => setProfile(e.target.value)}
          disabled={loading}
        >
          {profiles.map((p) => (
            <option key={p.key} value={p.key}>
              {p.label}
            </option>
          ))}
        </select>
        {selectedProfile && selectedProfile.sensitivity > 1 && (
          <span className="sensitivity-badge">
            {selectedProfile.sensitivity}× sensitivity
          </span>
        )}
      </div>

      {/* ── Advanced Settings ────────────────────────────────────── */}
      <button
        type="button"
        className="advanced-toggle"
        onClick={() => setShowAdvanced(!showAdvanced)}
      >
        {showAdvanced ? "▾" : "▸"} Advanced
      </button>

      {showAdvanced && (
        <div className="advanced-fields">
          <div className="input-row">
            <div className="input-group half">
              <label>Search Radius (km)</label>
              <input
                type="number"
                value={radiusKm}
                onChange={(e) => setRadiusKm(parseInt(e.target.value) || 100)}
                min={10}
                max={500}
                disabled={loading}
              />
            </div>
            <div className="input-group half">
              <label>FIRMS Lookback (days)</label>
              <input
                type="number"
                value={dayRange}
                onChange={(e) => setDayRange(parseInt(e.target.value) || 1)}
                min={1}
                max={10}
                disabled={loading}
              />
            </div>
          </div>
        </div>
      )}

      {/* ── Submit ───────────────────────────────────────────────── */}
      <button
        type="submit"
        className="submit-btn"
        disabled={loading || (mode === "polyline" ? !polyline.trim() : !origin.trim() || !destination.trim())}
      >
        {loading ? (
          <span className="loading-text">
            <span className="spinner" />
            Analyzing route…
          </span>
        ) : (
          <>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/>
            </svg>
            Score Route
          </>
        )}
      </button>
    </form>
  );
}