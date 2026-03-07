/**
 * config.js
 *
 * Centralised configuration for the frontend.
 * All magic numbers and tokens live here — nothing hardcoded in components.
 *
 * Env vars: Vite exposes anything prefixed with VITE_ from .env
 *   VITE_MAPBOX_TOKEN=pk.your_token_here
 */

// ─────────────────────────────────────────────────────────────────────────────
// MAPBOX
// ─────────────────────────────────────────────────────────────────────────────

export const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || "";

// Dark monochrome style — matches our gray UI theme
export const MAP_STYLE = "mapbox://styles/mapbox/dark-v11";

// Default view: Alberta, Canada (centered on Calgary–Banff corridor)
export const DEFAULT_CENTER = [-115.5, 51.15];
export const DEFAULT_ZOOM = 8;

// ─────────────────────────────────────────────────────────────────────────────
// L2 — TIME HORIZONS (must match hazard_field.py TIME_HORIZONS_HOURS)
// ─────────────────────────────────────────────────────────────────────────────

export const TIME_HORIZONS = [0, 1, 2, 4, 6];

// ─────────────────────────────────────────────────────────────────────────────
// L3 — RISK THRESHOLDS (must match route_scorer.py RISK_THRESHOLDS)
// ─────────────────────────────────────────────────────────────────────────────

export const RISK_THRESHOLDS = {
  safe: 0.15,
  moderate: 0.40,
  dangerous: 0.70,
};

// ─────────────────────────────────────────────────────────────────────────────
// SCORING DEFAULTS (must match ScoreRouteRequest defaults in scoring.py)
// ─────────────────────────────────────────────────────────────────────────────

export const SCORING_DEFAULTS = {
  radiusKm: 100,
  dayRange: 1,
  windSampleEvery: 5,
  aqiSampleEvery: 5,
  healthProfile: "default",
};

// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

// Empty in dev — Vite proxy handles routing to localhost:8000
// In production, set to your deployed backend URL
export const API_BASE = import.meta.env.VITE_API_BASE || "";