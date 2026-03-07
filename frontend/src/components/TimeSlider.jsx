// src/components/TimeSlider.jsx
// Row of buttons overlaid on the map for selecting which smoke projection
// time step to display (Now, +1h, +2h, +4h, +6h).

import config from "../config";

const LABELS = {
  0: "Now",
  1: "+1h",
  2: "+2h",
  4: "+4h",
  6: "+6h",
};

export default function TimeSlider({ selectedHours, onChange, visible }) {
  if (!visible) return null;

  return (
    <div className="time-slider">
      <span className="time-slider-label">Smoke Projection</span>
      <div className="time-slider-buttons">
        {config.TIME_HORIZONS.map((h) => (
          <button
            key={h}
            className={`time-btn ${selectedHours === h ? "active" : ""}`}
            onClick={() => onChange(h)}
            title={`Show smoke field at T+${h} hours`}
          >
            {LABELS[h] || `+${h}h`}
          </button>
        ))}
      </div>
    </div>
  );
}