// src/components/RouteInput.jsx
import { useState, useEffect } from "react";
import { getProfiles } from "../services/api";

export default function RouteInput({ onSubmit, loading }) {
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
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
    if (!origin.trim() || !destination.trim()) return;
    onSubmit({
      mode: "route",
      origin: origin.trim(),
      destination: destination.trim(),
      healthProfile: profile,
      radiusKm,
      dayRange,
    });
  };

  const selectedProfile = profiles.find((p) => p.key === profile);

  const inputClass =
    "w-full bg-neutral-900 border border-neutral-700 rounded px-2.5 py-2 text-sm text-neutral-100 " +
    "outline-none focus:border-neutral-500 transition-colors h-[40px]";

  return (
    <form onSubmit={handleSubmit} className="p-4 border-b border-neutral-800 flex flex-col gap-3">
      {/* Origin / Destination */}
      <div className="flex flex-col gap-2">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-medium text-neutral-500 uppercase tracking-wider">Origin</label>
          <input
            type="text"
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            placeholder="Example: Calgary, AB"
            disabled={loading}
            className={inputClass}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-medium text-neutral-500 uppercase tracking-wider">Destination</label>
          <input
            type="text"
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            placeholder="Example: Kamloops, BC"
            disabled={loading}
            className={inputClass}
          />
        </div>
      </div>

      {/* Health Profile */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-medium text-neutral-500 uppercase tracking-wider">Health Profile</label>
        <select 
          value={profile} 
          onChange={(e) => setProfile(e.target.value)} 
          disabled={loading} 
          className={`${inputClass} [color-scheme:dark]`}
        >
          {profiles.map((p) => (
            <option key={p.key} value={p.key}>{p.label}</option>
          ))}
        </select>
        {selectedProfile && selectedProfile.sensitivity > 1 && (
          <span className="inline-block mt-1 px-2 py-0.5 bg-neutral-800 border border-neutral-700 rounded text-neutral-400 text-[10px] font-medium w-fit">
            {selectedProfile.sensitivity}× sensitivity
          </span>
        )}
      </div>

      {/* Advanced */}
      <button
        type="button"
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-left text-neutral-500 text-[11px] hover:text-neutral-400 transition-colors bg-transparent border-none cursor-pointer"
      >
        {showAdvanced ? "▾" : "▸"} Advanced
      </button>

      {showAdvanced && (
        <div className="flex gap-2">
          <div className="flex-1 flex flex-col gap-1">
            <label className="text-[10px] font-medium text-neutral-500 uppercase tracking-wider">Radius (km)</label>
            <input
              type="number"
              value={radiusKm}
              onChange={(e) => setRadiusKm(parseInt(e.target.value) || 100)}
              min={10} max={500}
              disabled={loading}
              className={`${inputClass} [color-scheme:dark]`}
            />
          </div>
          <div className="flex-1 flex flex-col gap-1">
            <label className="text-[10px] font-medium text-neutral-500 uppercase tracking-wider">Lookback (days)</label>
            <input
              type="number"
              value={dayRange}
              onChange={(e) => setDayRange(parseInt(e.target.value) || 1)}
              min={1} max={10}
              disabled={loading}
              className={`${inputClass} [color-scheme:dark]`}
            />
          </div>
        </div>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={loading || !origin.trim() || !destination.trim()}
        className="w-full py-2.5 px-4 bg-neutral-200 hover:bg-neutral-100 disabled:opacity-50 disabled:cursor-not-allowed
          text-neutral-900 font-semibold text-sm rounded flex items-center justify-center gap-2
          transition-all hover:shadow-lg hover:shadow-neutral-200/20 active:translate-y-0"
      >
        {loading ? (
          <span className="flex items-center gap-2">
            <span className="w-3.5 h-3.5 border-2 border-neutral-900/25 border-t-neutral-900 rounded-full animate-spin" />
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