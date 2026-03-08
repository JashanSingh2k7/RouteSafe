// src/components/SidePanel.jsx
import { useState } from "react";
import RouteInput from "./RouteInput";
import { riskLabel } from "../services/mapUtils";

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
  isOptimizing, // 🟢 NEW
  error,
  onSubmit,
  onOptimize,   // 🟢 NEW
  onSegmentHover,
  hoveredSegment,
}) {
  const [expandedDose, setExpandedDose] = useState(false);

    
  
  return (
    <aside className="w-[380px] h-screen bg-neutral-950 border-r border-neutral-800 flex flex-col overflow-y-auto overflow-x-hidden
      scrollbar-thin scrollbar-thumb-neutral-800 scrollbar-track-transparent">

      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-neutral-800">
        <div className="flex items-center gap-2.5">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-neutral-400 shrink-0">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
          <div>
            <span className="block text-base font-bold tracking-tight text-neutral-100">RouteSafe</span>
            <span className="block text-[10px] text-neutral-500 font-normal uppercase tracking-wide">
              Wildfire-Aware Routing
            </span>
          </div>
        </div>
      </div>

      {/* Route Input */}
      <RouteInput onSubmit={onSubmit} loading={loading} />

      {/* Error */}
      {error && (
        <div className="mx-4 mt-3 p-3 bg-neutral-900 border border-neutral-700 rounded text-neutral-300 text-xs flex items-start gap-2">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 mt-0.5 text-neutral-500">
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
          <div className="p-4 border-b border-neutral-800">
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-neutral-500 mb-3">
              Risk Summary
            </h3>

            <div className="flex items-center gap-3 mb-3">
              <span className="px-3 py-1 rounded text-xs font-semibold uppercase tracking-wide bg-neutral-800 text-neutral-300 border border-neutral-700">
                {riskLabel(data.max_risk_score)}
              </span>
              <span className="text-neutral-400 text-xs">
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
                <div key={s.label} className="bg-neutral-900 rounded p-2.5">
                  <span className="block text-sm font-semibold tabular-nums text-neutral-100">{s.value}</span>
                  <span className="block text-[10px] text-neutral-500">{s.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 🟢 NEW: OPTIMIZE PATH CTA 🟢 */}
          {data.rerouted && data.waypoints?.length > 0 && (
            <div className="p-4 border-b border-neutral-800 bg-neutral-900/50">
              <div className="p-3 bg-neutral-900 border border-neutral-700 rounded flex flex-col gap-3 shadow-inner">
                <div className="flex items-start gap-2">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="mt-0.5 text-neutral-400 shrink-0">
                    <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                  <span className="text-xs text-neutral-300 leading-relaxed">
                    {data.briefing || "High-risk fire zones detected along this route. A safer detour is available."}
                  </span>
                </div>
                
                <button
                  onClick={onOptimize}
                  disabled={isOptimizing}
                  className="w-full py-2 bg-neutral-200 hover:bg-neutral-100 disabled:opacity-50 disabled:cursor-not-allowed
                    text-neutral-900 font-bold text-sm rounded flex items-center justify-center gap-2 transition-colors"
                >
                  {isOptimizing ? (
                    <>
                      <span className="w-3.5 h-3.5 border-2 border-neutral-900/25 border-t-neutral-900 rounded-full animate-spin" />
                      Calculating Detour...
                    </>
                  ) : (
                    "Optimize Path"
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Smoke Dose */}
          {data.smoke_dose && (
            <div className="p-4 border-b border-neutral-800">
              <h3 className="text-[10px] font-semibold uppercase tracking-widest text-neutral-500 mb-3 flex items-center">
                Smoke Exposure
                <span className="ml-auto text-[10px] font-normal normal-case tracking-normal text-neutral-500">
                  {data.smoke_dose.profile_label}
                </span>
              </h3>

              <div className="flex items-baseline gap-2 mb-3 p-3 bg-neutral-900 rounded-lg border-l-[3px] border-neutral-600">
                <span className="text-3xl font-bold tabular-nums text-neutral-300 leading-none">
                  {data.smoke_dose.cigarette_equivalents.toFixed(1)}
                </span>
                <span className="text-xs text-neutral-500">cigarette equivalents</span>
              </div>

              <div className="flex gap-1.5">
                {[
                  { val: data.smoke_dose.peak_pm25_ugm3.toFixed(0), unit: "µg/m³", label: "Peak PM2.5" },
                  { val: data.smoke_dose.avg_pm25_ugm3.toFixed(0), unit: "µg/m³", label: "Avg PM2.5" },
                  { val: data.smoke_dose.time_in_smoke_min.toFixed(0), unit: "min", label: "In smoke" },
                ].map((d) => (
                  <div key={d.label} className="flex-1 bg-neutral-900 rounded p-2 text-center">
                    <span className="block text-sm font-semibold tabular-nums text-neutral-100">{d.val}</span>
                    <span className="block text-[9px] text-neutral-500">{d.unit}</span>
                    <span className="block text-[9px] text-neutral-500 mt-0.5">{d.label}</span>
                  </div>
                ))}
              </div>

              {data.smoke_dose.health_advisory && (
                <>
                  <button
                    onClick={() => setExpandedDose(!expandedDose)}
                    className="mt-2 text-neutral-400 hover:text-neutral-300 text-[11px] font-medium bg-transparent border-none cursor-pointer transition-colors"
                  >
                    {expandedDose ? "▾" : "▸"} Health Advisory
                  </button>
                  {expandedDose && (
                    <div className="mt-2 p-3 bg-neutral-900 border border-neutral-800 rounded text-neutral-400 text-xs leading-relaxed">
                      {data.smoke_dose.health_advisory}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Segment List */}
          <div className="p-4 pb-2">
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-neutral-500 mb-3 flex items-center gap-2">
              Segments
              <span className="font-normal text-neutral-600">{data.scored_segments.length}</span>
            </h3>

            <div className="max-h-[280px] overflow-y-auto scrollbar-thin scrollbar-thumb-neutral-800 scrollbar-track-transparent">
              {data.scored_segments.map((seg) => {
                const isHovered = hoveredSegment === seg.index;
                const pct = (seg.risk_score * 100).toFixed(0);
                return (
                  <div
                    key={seg.index}
                    className={`flex items-center gap-2 py-1.5 px-1.5 rounded transition-colors cursor-default
                      ${isHovered ? "bg-neutral-800" : "hover:bg-neutral-800/50"}`}
                    onMouseEnter={() => onSegmentHover?.(seg.index)}
                    onMouseLeave={() => onSegmentHover?.(null)}
                  >
                    <span className="text-[10px] text-neutral-500 font-mono font-medium w-7 shrink-0">
                      #{seg.index}
                    </span>
                    <div className="flex-1 h-1.5 bg-neutral-800 rounded-full overflow-hidden">
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
                    <span className="text-[10px] text-neutral-500 font-mono w-[72px] text-right shrink-0">
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
        <div className="flex-1 flex flex-col items-center justify-center px-8 text-center text-neutral-500 text-xs gap-3">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" className="opacity-30 text-neutral-400">
            <path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
          </svg>
          <p>
            Paste an encoded polyline and hit{" "}
            <span className="text-neutral-300 font-medium">Score Route</span> to analyze
            wildfire and smoke hazards along your route.
          </p>
        </div>
      )}
    </aside>
  );
}