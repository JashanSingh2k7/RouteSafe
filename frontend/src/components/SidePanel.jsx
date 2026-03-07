// src/components/SidePanel.jsx
// Displays scoring results: risk summary stats, smoke dose report (cigarette equivalents),
// and a scrollable segment list with colored risk bars. Hover interaction syncs with map.

import { useState } from "react";
import RouteInput from "./RouteInput";
import { riskLevel } from "../services/geo";

// ── Helpers ──────────────────────────────────────────────────────────────────

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

// ── Component ────────────────────────────────────────────────────────────────

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
    <aside className="side-panel">
      {/* ── Header ────────────────────────────────────────────────────── */}
      <div className="panel-header">
        <div className="logo">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/>
            <path d="M2 17l10 5 10-5"/>
            <path d="M2 12l10 5 10-5"/>
          </svg>
          <div>
            <span className="logo-text">RouteSafe</span>
            <span className="logo-sub">Wildfire-Aware Routing</span>
          </div>
        </div>
      </div>

      {/* ── Route Input ───────────────────────────────────────────────── */}
      <RouteInput onSubmit={onSubmit} loading={loading} />

      {/* ── Error ─────────────────────────────────────────────────────── */}
      {error && (
        <div className="error-banner">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="15" y1="9" x2="9" y2="15"/>
            <line x1="9" y1="9" x2="15" y2="15"/>
          </svg>
          {error}
        </div>
      )}

      {/* ── Results ───────────────────────────────────────────────────── */}
      {data && (
        <div className="results">

          {/* ── Risk Summary ──────────────────────────────────────────── */}
          <div className="results-section">
            <h3 className="section-title">Risk Summary</h3>

            <div className="risk-badge-row">
              <span
                className="risk-badge"
                style={{
                  background: riskLevel(data.max_risk_score).color,
                  color: data.max_risk_score >= 0.4 ? "#fff" : "#0f172a",
                }}
              >
                {riskLevel(data.max_risk_score).label}
              </span>
              <span className="risk-pct">
                {(data.max_risk_score * 100).toFixed(0)}% peak risk
              </span>
            </div>

            <div className="stat-grid">
              <div className="stat">
                <span className="stat-value">{data.fire_count}</span>
                <span className="stat-label">Active fires</span>
              </div>
              <div className="stat">
                <span className="stat-value">{data.high_risk_count}</span>
                <span className="stat-label">Flagged segs</span>
              </div>
              <div className="stat">
                <span className="stat-value">{data.total_distance_km.toFixed(0)} km</span>
                <span className="stat-label">Distance</span>
              </div>
              <div className="stat">
                <span className="stat-value">{formatDuration(data.total_time_min)}</span>
                <span className="stat-label">Duration</span>
              </div>
            </div>
          </div>

          {/* ── Smoke Dose ────────────────────────────────────────────── */}
          {data.smoke_dose && (
            <div className="results-section dose-section">
              <h3 className="section-title">
                Smoke Exposure
                <span className="profile-tag">{data.smoke_dose.profile_label}</span>
              </h3>

              <div className="cigarette-hero">
                <span className="cig-number">
                  {data.smoke_dose.cigarette_equivalents.toFixed(1)}
                </span>
                <span className="cig-label">cigarette equivalents</span>
              </div>

              <div className="dose-stats">
                <div className="dose-stat">
                  <span className="dose-val">{data.smoke_dose.peak_pm25_ugm3.toFixed(0)}</span>
                  <span className="dose-unit">µg/m³</span>
                  <span className="dose-label">Peak PM2.5</span>
                </div>
                <div className="dose-stat">
                  <span className="dose-val">{data.smoke_dose.avg_pm25_ugm3.toFixed(0)}</span>
                  <span className="dose-unit">µg/m³</span>
                  <span className="dose-label">Avg PM2.5</span>
                </div>
                <div className="dose-stat">
                  <span className="dose-val">{data.smoke_dose.time_in_smoke_min.toFixed(0)}</span>
                  <span className="dose-unit">min</span>
                  <span className="dose-label">In smoke</span>
                </div>
              </div>

              {data.smoke_dose.health_advisory && (
                <button
                  className="advisory-toggle"
                  onClick={() => setExpandedDose(!expandedDose)}
                >
                  {expandedDose ? "▾" : "▸"} Health Advisory
                </button>
              )}
              {expandedDose && (
                <div className="advisory-text">
                  {data.smoke_dose.health_advisory}
                </div>
              )}
            </div>
          )}

          {/* ── Segment List ──────────────────────────────────────────── */}
          <div className="results-section segment-section">
            <h3 className="section-title">
              Segments
              <span className="seg-count">{data.scored_segments.length}</span>
            </h3>

            <div className="segment-list">
              {data.scored_segments.map((seg) => {
                const isHovered = hoveredSegment === seg.index;
                const pct = (seg.risk_score * 100).toFixed(0);
                return (
                  <div
                    key={seg.index}
                    className={`segment-row ${isHovered ? "hovered" : ""}`}
                    onMouseEnter={() => onSegmentHover?.(seg.index)}
                    onMouseLeave={() => onSegmentHover?.(null)}
                  >
                    <span className="seg-idx">#{seg.index}</span>
                    <div className="seg-bar-wrap">
                      <div
                        className="seg-bar"
                        style={{
                          width: `${Math.max(seg.risk_score * 100, 2)}%`,
                          background: riskBarColor(seg.risk_score),
                        }}
                      />
                    </div>
                    <span className="seg-pct" style={{ color: riskBarColor(seg.risk_score) }}>
                      {pct}%
                    </span>
                    <span className="seg-meta">
                      {seg.pm25_estimate
                        ? `${seg.pm25_estimate} µg/m³`
                        : "clean"}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ── Empty state ───────────────────────────────────────────────── */}
      {!data && !loading && !error && (
        <div className="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" opacity="0.4">
            <path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/>
          </svg>
          <p>Paste an encoded polyline and hit <strong>Score Route</strong> to analyze wildfire and smoke hazards along your route.</p>
        </div>
      )}
    </aside>
  );
}