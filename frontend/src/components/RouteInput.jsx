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
          { key: "asthma", label: "Asthma / respiratory", breathing_rate: 1.0, sensitivity: 2.0 },
          { key: "elderly", label: "Elderly (65+)", breathing_rate: 0.45, sensitivity: 1.4 },
          { key: "pregnant", label: "Pregnant", breathing_rate: 1.15, sensitivity: 1.3 },
          { key: "outdoor_worker", label: "Outdoor worker", breathing_rate: 1.8, sensitivity: 1.0 },
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
    "w-full bg-[#0f0f11] border border-[#1f1f23] rounded-sm px-3 py-2.5 text-[13px] text-[#e4e4e7] " +
    "placeholder-[#3f3f46] outline-none focus:border-[#3f3f46] transition-colors font-data";

  return (
    <form onSubmit={handleSubmit} className="p-4 border-b border-[#1f1f23] flex flex-col gap-3">
      <div className="flex flex-col gap-2.5">
        <div className="flex flex-col gap-1">
          <label className="text-[9px] font-semibold text-[#52525b] uppercase tracking-[0.12em]">Origin</label>
          <input
            type="text" value={origin} onChange={(e) => setOrigin(e.target.value)}
            placeholder="Calgary, AB" disabled={loading} className={inputClass}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[9px] font-semibold text-[#52525b] uppercase tracking-[0.12em]">Destination</label>
          <input
            type="text" value={destination} onChange={(e) => setDestination(e.target.value)}
            placeholder="Kamloops, BC" disabled={loading} className={inputClass}
          />
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[9px] font-semibold text-[#52525b] uppercase tracking-[0.12em]">Health Profile</label>
        <select value={profile} onChange={(e) => setProfile(e.target.value)}
          disabled={loading} className={`${inputClass} [color-scheme:dark]`}>
          {profiles.map((p) => (
            <option key={p.key} value={p.key}>{p.label}</option>
          ))}
        </select>
        {selectedProfile && selectedProfile.sensitivity > 1 && (
          <span className="inline-block mt-1 px-2 py-0.5 bg-[#141416] border border-[#1f1f23] rounded-sm text-[#71717a] text-[10px] font-data font-medium w-fit">
            {selectedProfile.sensitivity}x sensitivity
          </span>
        )}
      </div>

      <button type="button" onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-left text-[#52525b] text-[10px] hover:text-[#71717a] transition-colors bg-transparent border-none cursor-pointer font-medium tracking-wide uppercase">
        {showAdvanced ? "- " : "+ "}Advanced
      </button>

      {showAdvanced && (
        <div className="flex gap-2">
          <div className="flex-1 flex flex-col gap-1">
            <label className="text-[9px] font-semibold text-[#52525b] uppercase tracking-[0.12em]">Radius (km)</label>
            <input type="number" value={radiusKm} onChange={(e) => setRadiusKm(parseInt(e.target.value) || 100)}
              min={10} max={500} disabled={loading} className={`${inputClass} [color-scheme:dark]`} />
          </div>
          <div className="flex-1 flex flex-col gap-1">
            <label className="text-[9px] font-semibold text-[#52525b] uppercase tracking-[0.12em]">Lookback (days)</label>
            <input type="number" value={dayRange} onChange={(e) => setDayRange(parseInt(e.target.value) || 1)}
              min={1} max={10} disabled={loading} className={`${inputClass} [color-scheme:dark]`} />
          </div>
        </div>
      )}

      <button type="submit" disabled={loading || !origin.trim() || !destination.trim()}
        className="w-full py-2.5 px-4 bg-[#e4e4e7] hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed
          text-[#09090b] font-semibold text-[13px] rounded-sm flex items-center justify-center gap-2
          transition-all active:scale-[0.99]">
        {loading ? (
          <span className="flex items-center gap-2">
            <span className="w-3.5 h-3.5 border-2 border-[#09090b]/20 border-t-[#09090b] rounded-full animate-spin" />
            <span className="text-[#09090b]/70">Analyzing...</span>
          </span>
        ) : (
          <span className="tracking-wide">SCORE ROUTE</span>
        )}
      </button>
    </form>
  );
}