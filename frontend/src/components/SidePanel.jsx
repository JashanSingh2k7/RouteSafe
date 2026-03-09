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
  if (score < 0.15) return "#3f3f46";
  if (score < 0.30) return "#52525b";
  if (score < 0.40) return "#a16207";
  if (score < 0.60) return "#c2410c";
  if (score < 0.80) return "#b91c1c";
  return "#7f1d1d";
}

function riskBadgeBg(score) {
  if (score < 0.15) return "#27272a";
  if (score < 0.40) return "#422006";
  if (score < 0.70) return "#431407";
  return "#450a0a";
}

function riskBadgeText(score) {
  if (score < 0.15) return "#a1a1aa";
  if (score < 0.40) return "#fbbf24";
  if (score < 0.70) return "#fb923c";
  return "#fca5a5";
}

export default function SidePanel({
  data,
  optimizationResult,
  loading,
  optimizing,
  rerouting,
  error,
  onSubmit,
  onOptimize,
  onApplyReroute,
  canOptimize,
  onSegmentHover,
  hoveredSegment,
}) {
  const [expandedDose, setExpandedDose] = useState(false);
  const [expandedOptimizer, setExpandedOptimizer] = useState(false);

  const showOptimizeButton = Boolean((canOptimize || optimizing) && data);
  const showRerouteBanner = Boolean(
    optimizationResult?.rerouted && optimizationResult?.waypoints?.length > 0
  );

  return (
    <aside className="w-[380px] h-screen bg-[#09090b] border-r border-[#1f1f23] flex flex-col overflow-y-auto overflow-x-hidden">

      {/* ── Header ── */}
      <div className="px-4 pt-5 pb-4 border-b border-[#1f1f23]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-sm bg-[#141416] border border-[#1f1f23] flex items-center justify-center">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-[#71717a]">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <div>
            <span className="block text-[14px] font-bold tracking-tight text-[#e4e4e7]">RouteSafe</span>
            <span className="block text-[9px] text-[#52525b] font-semibold uppercase tracking-[0.15em]">
              Hazard-Aware Routing
            </span>
          </div>
        </div>
      </div>

      {/* ── Route Input ── */}
      <RouteInput onSubmit={onSubmit} loading={loading} />

      {/* ── Error ── */}
      {error && (
        <div className="mx-4 mt-3 p-3 bg-[#1c1917] border border-[#292524] rounded-sm text-[#fca5a5] text-[11px] flex items-start gap-2">
          <span className="text-[#ef4444] shrink-0 mt-px font-data text-[10px]">ERR</span>
          <span className="text-[#a1a1aa]">{error}</span>
        </div>
      )}

      {/* ── Results ── */}
      {data && (
        <div className="flex-1 flex flex-col">

          {/* Optimize button */}
          {showOptimizeButton && data.max_risk_score > 0 && (
            <div className="mx-4 mt-4">
              <button onClick={onOptimize} disabled={optimizing}
                className="w-full py-2.5 px-4 bg-[#1f1f23] hover:bg-[#27272a] border border-[#3f3f46] disabled:opacity-60
                  text-[#e4e4e7] font-semibold text-[12px] rounded-sm flex items-center justify-center gap-2
                  transition-all tracking-wide uppercase">
                {optimizing ? (
                  <span className="flex items-center gap-2">
                    <span className="w-3 h-3 border-2 border-[#52525b] border-t-[#e4e4e7] rounded-full animate-spin" />
                    <span className="text-[#a1a1aa] normal-case tracking-normal">Optimizing...</span>
                  </span>
                ) : (
                  <span>Optimize Route</span>
                )}
              </button>
              {data.high_risk_count > 0 && !optimizing && (
                <p className="text-[9px] text-[#52525b] text-center mt-2 tracking-wide">
                  {data.high_risk_count} segment{data.high_risk_count !== 1 ? "s" : ""} flagged
                </p>
              )}
            </div>
          )}

          {/* Reroute banner */}
          {showRerouteBanner && (
            <div className="mx-4 mt-4 p-3 bg-[#0f0f11] border border-[#1f1f23] rounded-sm">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-1.5 h-1.5 rounded-full bg-[#4ade80]" />
                <span className="text-[#a1a1aa] text-[10px] font-semibold uppercase tracking-[0.12em]">
                  Safer Route Found
                </span>
              </div>
              <p className="text-[#63636b] text-[11px] leading-relaxed mb-3">
                {optimizationResult?.briefing || "An optimized route is available."}
              </p>
              <button onClick={onApplyReroute} disabled={rerouting}
                className="w-full py-2 px-3 bg-[#1f1f23] hover:bg-[#27272a] border border-[#3f3f46] disabled:opacity-50
                  text-[#e4e4e7] text-[11px] font-semibold rounded-sm flex items-center justify-center gap-2
                  transition-colors tracking-wide uppercase">
                {rerouting ? (
                  <span className="flex items-center gap-2">
                    <span className="w-3 h-3 border-2 border-[#52525b] border-t-[#e4e4e7] rounded-full animate-spin" />
                    <span className="normal-case tracking-normal text-[#a1a1aa]">Applying...</span>
                  </span>
                ) : (
                  <span>Apply Route</span>
                )}
              </button>
            </div>
          )}

          {/* ── Risk Summary ── */}
          <div className="p-4 border-b border-[#1f1f23]">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[9px] font-semibold uppercase tracking-[0.15em] text-[#52525b]">Risk Summary</h3>
              <span className="font-data text-[10px] text-[#52525b]">
                {(data.max_risk_score * 100).toFixed(0)}% peak
              </span>
            </div>

            {/* Risk badge */}
            <div className="flex items-center gap-3 mb-4">
              <span className="px-3 py-1 rounded-sm text-[10px] font-bold uppercase tracking-[0.1em] font-data"
                style={{ background: riskBadgeBg(data.max_risk_score), color: riskBadgeText(data.max_risk_score) }}>
                {riskLabel(data.max_risk_score)}
              </span>
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 gap-px bg-[#1f1f23] rounded-sm overflow-hidden">
              {[
                { value: data.fire_count, label: "FIRES" },
                { value: data.high_risk_count, label: "FLAGGED" },
                { value: `${data.total_distance_km.toFixed(0)}km`, label: "DISTANCE" },
                { value: formatDuration(data.total_time_min), label: "DURATION" },
              ].map((s) => (
                <div key={s.label} className="bg-[#0f0f11] p-3">
                  <span className="block text-[15px] font-bold font-data text-[#e4e4e7] tabular-nums">{s.value}</span>
                  <span className="block text-[8px] font-semibold text-[#3f3f46] uppercase tracking-[0.15em] mt-0.5">{s.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* ── Smoke Dose ── */}
          {data.smoke_dose && (
            <div className="p-4 border-b border-[#1f1f23]">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[9px] font-semibold uppercase tracking-[0.15em] text-[#52525b]">Smoke Exposure</h3>
                <span className="text-[9px] text-[#3f3f46]">{data.smoke_dose.profile_label}</span>
              </div>

              {/* Cigarette metric */}
              <div className="flex items-baseline gap-2 mb-4 p-3 bg-[#0f0f11] border-l-2 border-[#a16207] rounded-sm">
                <span className="text-[28px] font-bold font-data tabular-nums text-[#e4e4e7] leading-none">
                  {data.smoke_dose.cigarette_equivalents.toFixed(1)}
                </span>
                <span className="text-[10px] text-[#52525b]">cigarette eq.</span>
              </div>

              {/* Dose stats */}
              <div className="grid grid-cols-3 gap-px bg-[#1f1f23] rounded-sm overflow-hidden">
                {[
                  { val: data.smoke_dose.peak_pm25_ugm3.toFixed(0), label: "PEAK" },
                  { val: data.smoke_dose.avg_pm25_ugm3.toFixed(0), label: "AVG" },
                  { val: `${data.smoke_dose.time_in_smoke_min.toFixed(0)}m`, label: "IN SMOKE" },
                ].map((d) => (
                  <div key={d.label} className="bg-[#0f0f11] p-2.5 text-center">
                    <span className="block text-[13px] font-bold font-data tabular-nums text-[#a1a1aa]">{d.val}</span>
                    <span className="block text-[7px] font-semibold text-[#3f3f46] uppercase tracking-[0.15em] mt-0.5">{d.label}</span>
                  </div>
                ))}
              </div>

              {/* Advisory */}
              {data.smoke_dose.health_advisory && (
                <>
                  <button onClick={() => setExpandedDose(!expandedDose)}
                    className="mt-3 text-[#52525b] text-[10px] font-medium bg-transparent border-none cursor-pointer hover:text-[#71717a] transition-colors tracking-wide uppercase">
                    {expandedDose ? "- " : "+ "}Advisory
                  </button>
                  {expandedDose && (
                    <div className="mt-2 p-3 bg-[#0f0f11] border border-[#1f1f23] rounded-sm text-[#63636b] text-[11px] leading-relaxed">
                      {data.smoke_dose.health_advisory}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* ── Optimizer Details ── */}
          {optimizationResult?.clusters_found > 0 && (
            <div className="p-4 border-b border-[#1f1f23]">
              <button onClick={() => setExpandedOptimizer(!expandedOptimizer)}
                className="w-full flex items-center gap-2 text-left bg-transparent border-none cursor-pointer">
                <h3 className="text-[9px] font-semibold uppercase tracking-[0.15em] text-[#52525b] flex items-center gap-2">
                  <span className="font-data">{expandedOptimizer ? "-" : "+"}</span>
                  Optimizer
                  <span className="font-data font-normal text-[#3f3f46]">
                    {optimizationResult.clusters_resolved}/{optimizationResult.clusters_found}
                  </span>
                </h3>
              </button>
              {expandedOptimizer && (
                <div className="mt-3 space-y-2">
                  {optimizationResult.avoidance_details?.map((d, i) => (
                    <div key={i} className="bg-[#0f0f11] border border-[#1f1f23] rounded-sm p-2.5">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[#a1a1aa] text-[11px] font-data">
                          seg {d.cluster_start}–{d.cluster_end}
                        </span>
                        <span className="text-[#3f3f46] text-[10px] font-data">
                          {d.cluster_peak_risk ? `${(d.cluster_peak_risk * 100).toFixed(0)}%` : ""}
                        </span>
                      </div>
                      <div className="flex gap-4 text-[9px] text-[#3f3f46] font-data">
                        <span>+{d.detour_km?.toFixed(0)}km</span>
                        <span>{d.original_severity_sum?.toFixed(1)} &rarr; {d.new_severity_sum?.toFixed(1)}</span>
                        {d.improvement_pct && <span>{d.improvement_pct}% better</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── Segments ── */}
          {data.scored_segments?.length > 0 && (
            <div className="p-4 flex-1 min-h-0">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-[9px] font-semibold uppercase tracking-[0.15em] text-[#52525b]">Segments</h3>
                <span className="text-[9px] font-data text-[#3f3f46]">{data.scored_segments.length}</span>
              </div>

              <div className="space-y-px">
                {data.scored_segments.map((seg) => {
                  const isHovered = hoveredSegment === seg.index;
                  const pct = (seg.risk_score * 100).toFixed(0);
                  return (
                    <div key={seg.index}
                      className={`flex items-center gap-2 py-1.5 px-2 rounded-sm transition-colors cursor-default
                        ${isHovered ? "bg-[#1a1a1d]" : "hover:bg-[#0f0f11]"}`}
                      onMouseEnter={() => onSegmentHover?.(seg.index)}
                      onMouseLeave={() => onSegmentHover?.(null)}>
                      <span className="text-[9px] text-[#3f3f46] font-data font-medium w-6 shrink-0 tabular-nums">
                        {seg.index}
                      </span>
                      <div className="flex-1 h-[3px] bg-[#141416] rounded-sm overflow-hidden">
                        <div className="h-full rounded-sm transition-[width] duration-300"
                          style={{
                            width: `${Math.max(seg.risk_score * 100, 3)}%`,
                            background: riskBarColor(seg.risk_score),
                          }} />
                      </div>
                      <span className="text-[10px] font-data font-semibold tabular-nums w-8 text-right shrink-0"
                        style={{ color: riskBarColor(seg.risk_score) }}>
                        {pct}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Empty state ── */}
      {!data && !loading && !error && (
        <div className="flex-1 flex flex-col items-center justify-center px-10 text-center gap-4">
          <div className="w-10 h-10 rounded-sm bg-[#0f0f11] border border-[#1f1f23] flex items-center justify-center">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-[#3f3f46]">
              <path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
          </div>
          <p className="text-[#3f3f46] text-[11px] leading-relaxed">
            Enter origin and destination to analyze wildfire and smoke hazards along your route.
          </p>
        </div>
      )}
    </aside>
  );
}