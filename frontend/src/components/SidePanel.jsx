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

function snowSeverityColor(severity) {
  const map = { low: "#93c5fd", moderate: "#60a5fa", high: "#3b82f6", critical: "#1e3a8a" };
  return map[severity] || "#93c5fd";
}

export default function SidePanel({
  data,
  loading,
  optimizing,
  rerouting,
  error,
  onSubmit,
  onOptimize,
  onApplyReroute,
  canOptimize,
  hazardView,
  onHazardViewChange,
  onSegmentHover,
  hoveredSegment,
}) {
  const [expandedDose, setExpandedDose] = useState(false);
  const [expandedOptimizer, setExpandedOptimizer] = useState(false);
  const [expandedSnow, setExpandedSnow] = useState(false);

  const isOptimized = data && ("rerouted" in data);
  const hasSnow = data?.snow_count > 0 || (data?.snow_hazards?.length > 0);
  const hasFire = data?.fire_count > 0;

  return (
    <aside className="w-[380px] h-screen bg-neutral-900 border-r border-gray-800 flex flex-col overflow-y-auto overflow-x-hidden
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

          {/* ── Hazard View Toggle ────────────────────────────────────── */}
          {(hasFire || hasSnow) && (
            <div className="mx-4 mt-3">
              <div className="flex bg-gray-800 rounded p-0.5">
                {[
                  { key: "all", label: "All" },
                  { key: "fire", label: "Fire / Smoke" },
                  { key: "snow", label: "Snow / Ice" },
                ].map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() => onHazardViewChange(key)}
                    className={`flex-1 py-1.5 text-[10px] font-semibold uppercase tracking-wide rounded transition-colors
                      ${hazardView === key
                        ? key === "snow"
                          ? "bg-blue-600 text-white"
                          : key === "fire"
                            ? "bg-amber-600 text-white"
                            : "bg-gray-600 text-white"
                        : "text-gray-400 hover:text-gray-300"
                      }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* ── Optimize Route Button ── */}
          {canOptimize && data.max_risk_score > 0 && (
            <div className="mx-4 mt-3">
              <button
                onClick={onOptimize}
                disabled={optimizing}
                className="w-full py-2.5 px-4 bg-amber-600 hover:bg-amber-500 disabled:opacity-50
                  text-white font-semibold text-sm rounded flex items-center justify-center gap-2
                  transition-colors"
              >
                {optimizing ? (
                  <span className="flex items-center gap-2">
                    <span className="w-3.5 h-3.5 border-2 border-white/25 border-t-white rounded-full animate-spin" />
                    Optimizing...
                  </span>
                ) : (
                  <>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                    Optimize Route
                  </>
                )}
              </button>
              {data.high_risk_count > 0 && (
                <p className="text-[10px] text-gray-500 text-center mt-1.5">
                  {data.high_risk_count} segment{data.high_risk_count !== 1 ? "s" : ""} flagged — find a safer path
                </p>
              )}
            </div>
          )}

          {/* ── Reroute Banner ── */}
          {isOptimized && data.rerouted && data.waypoints?.length > 0 && (
            <div className="mx-4 mt-3 p-3 bg-emerald-500/10 border border-emerald-500/25 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-emerald-400 shrink-0">
                  <path d="M9 18l6-6-6-6" />
                </svg>
                <span className="text-emerald-300 text-xs font-semibold uppercase tracking-wide">
                  Safer Route Available
                </span>
              </div>
              <p className="text-gray-400 text-[11px] leading-relaxed mb-3">
                {data.briefing}
              </p>
              <button
                onClick={onApplyReroute}
                disabled={rerouting}
                className="w-full py-2 px-3 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50
                  text-white text-xs font-semibold rounded flex items-center justify-center gap-2
                  transition-colors"
              >
                {rerouting ? (
                  <span className="flex items-center gap-2">
                    <span className="w-3 h-3 border-2 border-white/25 border-t-white rounded-full animate-spin" />
                    Applying...
                  </span>
                ) : (
                  <>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                    Apply Safer Route
                  </>
                )}
              </button>
            </div>
          )}

          {/* ── Clean route after L4 ── */}
          {isOptimized && !data.rerouted && (
            <div className="mx-4 mt-3 p-3 bg-gray-800/50 border border-gray-700/50 rounded-lg">
              <div className="flex items-center gap-2">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="text-green-400 shrink-0">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <span className="text-gray-300 text-xs">
                  {data.briefing || "Route is within acceptable risk levels."}
                </span>
              </div>
            </div>
          )}

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
                { value: data.snow_count ?? 0, label: "Snow/ice zones" },
                { value: data.high_risk_count, label: "Flagged segs" },
                { value: formatDuration(data.total_time_min), label: "Duration" },
                { value: `${data.total_distance_km.toFixed(0)} km`, label: "Distance" },
              ].filter((s) => s.value !== undefined).map((s) => (
                <div key={s.label} className="bg-gray-900 rounded p-2.5">
                  <span className="block text-sm font-semibold tabular-nums text-gray-100">{s.value}</span>
                  <span className="block text-[10px] text-gray-500">{s.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Snow / Ice Conditions */}
          {hasSnow && (
            <div className="p-4 border-b border-gray-800">
              <button
                onClick={() => setExpandedSnow(!expandedSnow)}
                className="w-full flex items-center gap-2 text-left bg-transparent border-none cursor-pointer"
              >
                <h3 className="text-[10px] font-semibold uppercase tracking-widest text-gray-500 flex items-center gap-2">
                  <span>{expandedSnow ? "▾" : "▸"}</span>
                  Snow / Ice Conditions
                  <span className="font-normal text-blue-400">
                    {data.snow_hazards?.length || data.snow_count || 0} zone{(data.snow_hazards?.length || 0) !== 1 ? "s" : ""}
                  </span>
                </h3>
              </button>

              {expandedSnow && data.snow_hazards?.length > 0 && (
                <div className="mt-3 space-y-2">
                  {/* Group by type */}
                  {(() => {
                    const byType = {};
                    for (const h of data.snow_hazards) {
                      const key = h.hazard_type === "black_ice" ? "Black Ice" : "Snow";
                      if (!byType[key]) byType[key] = { count: 0, severities: {}, temps: [] };
                      byType[key].count++;
                      byType[key].severities[h.severity] = (byType[key].severities[h.severity] || 0) + 1;
                      if (h.metadata?.temperature_c != null) byType[key].temps.push(h.metadata.temperature_c);
                    }
                    return Object.entries(byType).map(([type, info]) => (
                      <div key={type} className="bg-gray-900 rounded p-2.5 text-xs">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-gray-200 font-medium">{type}</span>
                          <span className="text-gray-500">{info.count} reading{info.count !== 1 ? "s" : ""}</span>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {Object.entries(info.severities).map(([sev, count]) => (
                            <span
                              key={sev}
                              className="px-2 py-0.5 rounded text-[10px] font-medium uppercase"
                              style={{ background: snowSeverityColor(sev), color: sev === "critical" || sev === "high" ? "#fff" : "#1e3a5f" }}
                            >
                              {sev} ({count})
                            </span>
                          ))}
                        </div>
                        {info.temps.length > 0 && (
                          <div className="mt-1.5 text-[10px] text-gray-500">
                            Temp range: {Math.min(...info.temps).toFixed(0)}°C to {Math.max(...info.temps).toFixed(0)}°C
                          </div>
                        )}
                      </div>
                    ));
                  })()}
                </div>
              )}
            </div>
          )}

          {/* Smoke Dose */}
          {data.smoke_dose && (
            <div className="p-4 border-b border-gray-800">
              <h3 className="text-[10px] font-semibold uppercase tracking-widest text-gray-500 mb-3 flex items-center">
                Smoke Exposure
                <span className="ml-auto text-[10px] font-normal normal-case tracking-normal text-gray-500">
                  {data.smoke_dose.profile_label}
                </span>
              </h3>

              <div className="flex items-baseline gap-2 mb-3 p-3 bg-gray-900 rounded-lg border-l-[3px] border-amber-500">
                <span className="text-3xl font-bold tabular-nums text-amber-500 leading-none">
                  {data.smoke_dose.cigarette_equivalents.toFixed(1)}
                </span>
                <span className="text-xs text-gray-400">cigarette equivalents</span>
              </div>

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

          {/* L4 Optimizer Details */}
          {isOptimized && data.clusters_found > 0 && (
            <div className="p-4 border-b border-gray-800">
              <button
                onClick={() => setExpandedOptimizer(!expandedOptimizer)}
                className="w-full flex items-center gap-2 text-left bg-transparent border-none cursor-pointer"
              >
                <h3 className="text-[10px] font-semibold uppercase tracking-widest text-gray-500 flex items-center gap-2">
                  <span>{expandedOptimizer ? "▾" : "▸"}</span>
                  Optimizer Details
                  <span className="font-normal text-gray-600">
                    {data.clusters_resolved}/{data.clusters_found} resolved
                  </span>
                </h3>
              </button>

              {expandedOptimizer && (
                <div className="mt-3 space-y-2">
                  {data.avoidance_details?.map((d, i) => (
                    <div key={i} className="bg-gray-900 rounded p-2.5 text-xs">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-gray-300 font-medium">
                          Segments {d.cluster_start}–{d.cluster_end}
                        </span>
                        <span className="text-gray-500">
                          {d.cluster_peak_risk ? `${(d.cluster_peak_risk * 100).toFixed(0)}% peak` : ""}
                        </span>
                      </div>
                      <div className="flex gap-3 text-[10px] text-gray-500">
                        <span>Detour: {d.detour_km?.toFixed(1)} km</span>
                        <span>
                          Severity: {d.original_severity_sum?.toFixed(1)} → {d.new_severity_sum?.toFixed(1)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
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
            Enter an origin and destination, then hit{" "}
            <span className="text-gray-300 font-medium">Score Route</span> to analyze
            wildfire, smoke, snow, and ice hazards along your route.
          </p>
        </div>
      )}
    </aside>
  );
}