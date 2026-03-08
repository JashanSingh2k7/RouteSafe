// src/components/TimeSlider.jsx
import { TIME_HORIZONS } from "../config";

const LABELS = { 0: "Now", 1: "+1h", 2: "+2h", 4: "+4h", 6: "+6h" };

export default function TimeSlider({ selectedHours, onChange, visible }) {
  if (!visible) return null;

  return (
    <div className="absolute top-3.5 left-1/2 -translate-x-1/2 z-10
      flex items-center gap-2.5 bg-gray-950/90 backdrop-blur-lg
      border border-gray-800 rounded-lg px-3 py-1.5">
      <span className="text-[10px] text-gray-500 uppercase tracking-wide font-medium whitespace-nowrap">
        Smoke Projection
      </span>
      <div className="flex gap-1">
        {TIME_HORIZONS.map((h) => (
          <button
            key={h}
            onClick={() => onChange(h)}
            title={`Show smoke field at T+${h} hours`}
            className={`px-3 py-1 rounded text-[11px] font-mono font-medium border transition-all
              ${selectedHours === h
                ? "bg-amber-500 text-gray-950 border-amber-500 font-semibold"
                : "bg-transparent text-gray-400 border-transparent hover:bg-gray-800 hover:text-gray-200"
              }`}
          >
            {LABELS[h] || `+${h}h`}
          </button>
        ))}
      </div>
    </div>
  );
}