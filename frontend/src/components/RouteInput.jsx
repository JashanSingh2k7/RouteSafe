// src/components/RouteInput.jsx
import { useState, useEffect } from "react";
import { getProfiles } from "../services/api";

export default function RouteInput({ onSubmit, loading }) {
  const [mode, setMode] = useState("polyline");
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
        encodedPolyline: polyline.trim(),
        totalDurationMin: parseFloat(durationMin) || 120,
        radiusKm,
        dayRange,
        healthProfile: profile,
      });
    } else {
      if (!origin.trim() || !destination.trim()) return;
      onSubmit({
        mode: "route",
        origin: origin.trim(),
        destination: destination.trim(),
        healthProfile: profile,
        radiusKm,
        dayRange,
      });
    }
  };

  const selectedProfile = profiles.find((p) => p.key === profile);

  const inputClass =
    "w-full bg-gray-800 border border-gray-700 rounded px-2.5 py-2 text-sm text-gray-200 " +
    "outline-none focus:border-gray-500 transition-colors";

  return (
    <form onSubmit={handleSubmit} className="p-4 border-b border-gray-800 flex flex-col gap-3">
      {/* Mode Toggle */}
      <div className="flex bg-gray-800/60 rounded p-0.5 gap-0.5">
        <button
          type="button"
          onClick={() => setMode("route")}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded text-xs font-medium transition-all ${
            mode === "route"
              ? "bg-gray-700 text-gray-100 shadow-sm"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" />
            <circle cx="12" cy="9" r="2.5" />
          </svg>
          Route
        </button>
        <button
          type="button"
          onClick={() => setMode("polyline")}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded text-xs font-medium transition-all ${
            mode === "polyline"
              ? "bg-gray-700 text-gray-100 shadow-sm"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="4 17 10 11 4 5" />
            <line x1="12" y1="19" x2="20" y2="19" />
          </svg>
          Polyline
        </button>
      </div>

      {/* Route Mode */}
      {mode === "route" && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Origin</label>
            <input
              type="text"
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              placeholder="Calgary, AB"
              disabled={loading}
              className={inputClass}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Destination</label>
            <input
              type="text"
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              placeholder="Kamloops, BC"
              disabled={loading}
              className={inputClass}
            />
          </div>
        </div>
      )}

      {/* Polyline Mode */}
      {mode === "polyline" && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Encoded Polyline</label>
            <textarea
              value={polyline}
              onChange={(e) => setPolyline(e.target.value)}
              placeholder="Paste a Google Directions encoded polyline..."
              rows={3}
              disabled={loading}
              spellCheck={false}
              className={`${inputClass} resize-y min-h-[52px] font-mono text-[11px]`}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Trip Duration (min)</label>
            <input
              type="number"
              value={durationMin}
              onChange={(e) => setDurationMin(e.target.value)}
              min={1}
              max={2880}
              disabled={loading}
              className={inputClass}
            />
          </div>
        </div>
      )}

      {/* Health Profile */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Health Profile</label>
        <select value={profile} onChange={(e) => setProfile(e.target.value)} disabled={loading} className={inputClass}>
          {profiles.map((p) => (
            <option key={p.key} value={p.key}>{p.label}</option>
          ))}
        </select>
        {selectedProfile && selectedProfile.sensitivity > 1 && (
          <span className="inline-block mt-1 px-2 py-0.5 bg-amber-500/10 border border-amber-500/25 rounded text-amber-400 text-[10px] font-medium w-fit">
            {selectedProfile.sensitivity}× sensitivity
          </span>
        )}
      </div>

      {/* Advanced */}
      <button
        type="button"
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-left text-gray-500 text-[11px] hover:text-gray-400 transition-colors bg-transparent border-none cursor-pointer"
      >
        {showAdvanced ? "▾" : "▸"} Advanced
      </button>

      {showAdvanced && (
        <div className="flex gap-2">
          <div className="flex-1 flex flex-col gap-1">
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Radius (km)</label>
            <input
              type="number"
              value={radiusKm}
              onChange={(e) => setRadiusKm(parseInt(e.target.value) || 100)}
              min={10} max={500}
              disabled={loading}
              className={inputClass}
            />
          </div>
          <div className="flex-1 flex flex-col gap-1">
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Lookback (days)</label>
            <input
              type="number"
              value={dayRange}
              onChange={(e) => setDayRange(parseInt(e.target.value) || 1)}
              min={1} max={10}
              disabled={loading}
              className={inputClass}
            />
          </div>
        </div>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={loading || (mode === "polyline" ? !polyline.trim() : !origin.trim() || !destination.trim())}
        className="w-full py-2.5 px-4 bg-amber-500 hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed
          text-gray-950 font-semibold text-sm rounded flex items-center justify-center gap-2
          transition-all hover:shadow-lg hover:shadow-amber-500/20 active:translate-y-0"
      >
        {loading ? (
          <span className="flex items-center gap-2">
            <span className="w-3.5 h-3.5 border-2 border-gray-950/25 border-t-gray-950 rounded-full animate-spin" />
            Analyzing route…
          </span>
        ) : (
          <>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
            Score Route
          </>
        )}
      </button>
    </form>
  );
}