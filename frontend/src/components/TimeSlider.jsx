// src/components/TimeSlider.jsx
import { TIME_HORIZONS } from "../config";

const LABELS = { 0: "NOW", 1: "+1H", 2: "+2H", 4: "+4H", 6: "+6H" };

export default function TimeSlider({ selectedHours, onChange, visible }) {
  if (!visible) return null;

  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10
      flex items-center gap-3 bg-[#09090b]/95 backdrop-blur-sm
      border border-[#1f1f23] rounded-sm px-3 py-1.5">
      <span className="text-[8px] text-[#3f3f46] uppercase tracking-[0.15em] font-semibold whitespace-nowrap">
        Projection
      </span>
      <div className="flex gap-0.5">
        {TIME_HORIZONS.map((h) => (
          <button
            key={h}
            onClick={() => onChange(h)}
            className={`px-2.5 py-1 rounded-sm text-[10px] font-data font-semibold border transition-all
              ${selectedHours === h
                ? "bg-[#e4e4e7] text-[#09090b] border-[#e4e4e7]"
                : "bg-transparent text-[#52525b] border-transparent hover:bg-[#141416] hover:text-[#a1a1aa]"
              }`}
          >
            {LABELS[h] || `+${h}H`}
          </button>
        ))}
      </div>
    </div>
  );
}