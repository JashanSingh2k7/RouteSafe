// src/components/SidePanel.jsx
import { useState } from "react";
import RouteInput from "./RouteInput";
import { riskLabel, riskColor } from "../services/mapUtils";

function formatDuration(min) {
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function riskBarColor(score) {
  if (score < 0.15) return "#22c55e";
  if (score < 0.30) return "#84cc16";
  if (score < 0.40) return "#f59e0b";
  if (score < 0.60) return "#f97316";
  if (score < 0.80) return "#ef4444";
  return "#7c2d12";
}

export default function SidePanel({
  data,
  loading,
  error,
  onSubmit,
  onSegmentHover,
  hoveredSegment,
}) {
  const [expandedDose, setExpandedDose] = useState(false);

  return (
    <aside className="w-[380px] h-screen bg-gray-950 border-r border-gray-800 flex flex-col overflow-y-auto overflow-x-hidden
      scrollbar-thin scrollbar-thumb-gray-800 scrollbar-track-transparent">

      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-gray-800">
        <div className="flex items-center gap-2.5">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-amber-500 shrink-0">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
          <div>
            <span className="block text-base font-bold tracking-tight text-gray-100">RouteSafe</span>
            <span className="block text-[10px] text-gray-500 font-normal uppercase tracking-wide">
              Wildfire-Aware Routing
            </span>
          </div>
        </div>
      </div>

      {/* Route Input */}
      <RouteInput onSubmit={onSubmit} loading={loading} />

      {/* Error */}
      {error && (
        <div className="mx-4 mt-3 p-3 bg-red-500/10 border border-red-500/25 rounded text-red-300 text-xs flex items-start gap-2">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 mt-0.5">
            <circle cx="12" cy="12" r="10" />
            <line x1="15" y1="9" x2="9" y2="15" />
            <line x1="9" y1="9" x2="15" y2="15" />
          </svg>
          {error}
        </div>
      )}

      {/* Results */}
      {data && (
        <div className="flex-1 flex flex-col">

          {/* Risk Summary */}
          <div className="p-4 border-b border-gray-800">
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-gray-500 mb-3">
              Risk Summary
            </h3>

            <div className="flex items-center gap-3 mb-3">
              <span
                className="px-3 py-1 rounded text-xs font-semibold uppercase tracking-wide"
                style={{
                  background: riskColor(data.max_risk_score),
                  color: data.max_risk_score >= 0.4 ? "#fff" : "#0f172a",
                }}
              >
                {riskLabel(data.max_risk_score)}
              </span>
              <span className="text-gray-400 text-xs">
                {(data.max_risk_score * 100).toFixed(0)}% peak risk
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2">
              {[
                { value: data.fire_count, label: "Active fires" },
                { value: data.high_risk_count, label: "Flagged segs" },
                { value: `${data.total_distance_km.toFixed(0)} km`, label: "Distance" },
                { value: formatDuration(data.total_time_min), label: "Duration" },
              ].map((s) => (
                <div key={s.label} className="bg-gray-900 rounded p-2.5">
                  <span className="block text-sm font-semibold tabular-nums text-gray-100">{s.value}</span>
                  <span className="block text-[10px] text-gray-500">{s.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Smoke Dose */}
          {data.smoke_dose && (
            <div className="p-4 border-b border-gray-800">
              <h3 className="text-[10px] font-semibold uppercase tracking-widest text-gray-500 mb-3 flex items-center">
                Smoke Exposure
                <span className="ml-auto text-[10px] font-normal normal-case tracking-normal text-gray-500">
                  {data.smoke_dose.profile_label}
                </span>
              </h3>

              {/* Cigarette hero */}
              <div className="flex items-baseline gap-2 mb-3 p-3 bg-gray-900 rounded-lg border-l-[3px] border-amber-500">
                <span className="text-3xl font-bold tabular-nums text-amber-500 leading-none">
                  {data.smoke_dose.cigarette_equivalents.toFixed(1)}
                </span>
                <span className="text-xs text-gray-400">cigarette equivalents</span>
              </div>

              {/* Dose stats */}
              <div className="flex gap-1.5">
                {[
                  { val: data.smoke_dose.peak_pm25_ugm3.toFixed(0), unit: "µg/m³", label: "Peak PM2.5" },
                  { val: data.smoke_dose.avg_pm25_ugm3.toFixed(0), unit: "µg/m³", label: "Avg PM2.5" },
                  { val: data.smoke_dose.time_in_smoke_min.toFixed(0), unit: "min", label: "In smoke" },
                ].map((d) => (
                  <div key={d.label} className="flex-1 bg-gray-900 rounded p-2 text-center">
                    <span className="block text-sm font-semibold tabular-nums text-gray-100">{d.val}</span>
                    <span className="block text-[9px] text-gray-500">{d.unit}</span>
                    <span className="block text-[9px] text-gray-500 mt-0.5">{d.label}</span>
                  </div>
                ))}
              </div>

              {/* Advisory */}
              {data.smoke_dose.health_advisory && (
                <>
                  <button
                    onClick={() => setExpandedDose(!expandedDose)}
                    className="mt-2 text-amber-400 text-[11px] font-medium bg-transparent border-none cursor-pointer hover:opacity-80 transition-opacity"
                  >
                    {expandedDose ? "▾" : "▸"} Health Advisory
                  </button>
                  {expandedDose && (
                    <div className="mt-2 p-3 bg-amber-500/5 border border-amber-500/15 rounded text-gray-400 text-xs leading-relaxed">
                      {data.smoke_dose.health_advisory}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Segment List */}
          <div className="p-4 pb-2">
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-gray-500 mb-3 flex items-center gap-2">
              Segments
              <span className="font-normal text-gray-600">{data.scored_segments.length}</span>
            </h3>

            <div className="max-h-[280px] overflow-y-auto scrollbar-thin scrollbar-thumb-gray-800 scrollbar-track-transparent">
              {data.scored_segments.map((seg) => {
                const isHovered = hoveredSegment === seg.index;
                const pct = (seg.risk_score * 100).toFixed(0);
                return (
                  <div
                    key={seg.index}
                    className={`flex items-center gap-2 py-1.5 px-1.5 rounded transition-colors cursor-default
                      ${isHovered ? "bg-gray-800" : "hover:bg-gray-800/50"}`}
                    onMouseEnter={() => onSegmentHover?.(seg.index)}
                    onMouseLeave={() => onSegmentHover?.(null)}
                  >
                    <span className="text-[10px] text-gray-500 font-mono font-medium w-7 shrink-0">
                      #{seg.index}
                    </span>
                    <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-[width] duration-300"
                        style={{
                          width: `${Math.max(seg.risk_score * 100, 2)}%`,
                          background: riskBarColor(seg.risk_score),
                        }}
                      />
                    </div>
                    <span
                      className="text-[11px] font-semibold tabular-nums w-8 text-right shrink-0"
                      style={{ color: riskBarColor(seg.risk_score) }}
                    >
                      {pct}%
                    </span>
                    <span className="text-[10px] text-gray-500 font-mono w-[72px] text-right shrink-0">
                      {seg.pm25_estimate ? `${seg.pm25_estimate} µg/m³` : "clean"}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!data && !loading && !error && (
        <div className="flex-1 flex flex-col items-center justify-center px-8 text-center text-gray-500 text-xs gap-3">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" className="opacity-30">
            <path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
          </svg>
          <p>
            Paste an encoded polyline and hit{" "}
            <span className="text-gray-300 font-medium">Score Route</span> to analyze
            wildfire and smoke hazards along your route.
          </p>
        </div>
      )}
    </aside>
  );
}