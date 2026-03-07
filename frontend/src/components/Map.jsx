// src/components/Map.jsx
// Mapbox GL map — renders route segments (risk-colored), smoke polygons, and fire markers.
// Updates layers when new data arrives. Handles hover popups on route segments.

import { useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import config from "../config";
import {
  segmentsToGeoJSON,
  polygonsToGeoJSON,
  firesToGeoJSON,
} from "../services/geo";

// ── Layer IDs ────────────────────────────────────────────────────────────────
const ROUTE_SOURCE = "route-segments";
const ROUTE_LAYER = "route-segments-line";
const ROUTE_CASING = "route-segments-casing";
const SMOKE_SOURCE = "smoke-polygons";
const SMOKE_LAYER = "smoke-polygons-fill";
const SMOKE_OUTLINE = "smoke-polygons-outline";
const FIRE_SOURCE = "fire-markers";
const FIRE_LAYER = "fire-markers-circle";
const FIRE_PULSE = "fire-markers-pulse";

const EMPTY_FC = { type: "FeatureCollection", features: [] };

export default function Map({
  scoredSegments,
  hazardPolygons,
  selectedHours,
  hoveredSegment,
  onSegmentHover,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);
  const readyRef = useRef(false);

  // ── Initialize map ───────────────────────────────────────────────────────
  useEffect(() => {
    if (mapRef.current) return;

    mapboxgl.accessToken = config.MAPBOX_TOKEN;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: config.MAP_CENTER,
      zoom: config.MAP_ZOOM,
      pitch: 0,
      antialias: true,
    });

    map.addControl(new mapboxgl.NavigationControl(), "bottom-right");
    map.addControl(
      new mapboxgl.ScaleControl({ unit: "metric" }),
      "bottom-left"
    );

    map.on("load", () => {
      // ── Smoke polygon source + layers ────────────────────────────────
      map.addSource(SMOKE_SOURCE, {
        type: "geojson",
        data: EMPTY_FC,
      });

      map.addLayer({
        id: SMOKE_LAYER,
        type: "fill",
        source: SMOKE_SOURCE,
        paint: {
          "fill-color": [
            "match",
            ["get", "severity"],
            "low", "rgba(156,163,175,0.12)",
            "moderate", "rgba(156,163,175,0.25)",
            "high", "rgba(107,114,128,0.38)",
            "critical", "rgba(75,85,99,0.50)",
            "rgba(156,163,175,0.18)",
          ],
          "fill-opacity": 0.8,
        },
      });

      map.addLayer({
        id: SMOKE_OUTLINE,
        type: "line",
        source: SMOKE_SOURCE,
        paint: {
          "line-color": "rgba(156,163,175,0.35)",
          "line-width": 1,
          "line-dasharray": [2, 2],
        },
      });

      // ── Route segment source + layers ────────────────────────────────
      map.addSource(ROUTE_SOURCE, {
        type: "geojson",
        data: EMPTY_FC,
      });

      // Casing (dark outline beneath the colored line)
      map.addLayer({
        id: ROUTE_CASING,
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": "#0f172a",
          "line-width": 7,
          "line-opacity": 0.7,
        },
      });

      // Main risk-colored route line
      map.addLayer({
        id: ROUTE_LAYER,
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": [
            "interpolate",
            ["linear"],
            ["get", "risk_score"],
            ...config.SEGMENT_COLOR_STOPS.flat(),
          ],
          "line-width": [
            "case",
            ["boolean", ["feature-state", "hover"], false],
            6,
            4,
          ],
          "line-opacity": 1,
        },
      });

      // ── Fire marker source + layers ──────────────────────────────────
      map.addSource(FIRE_SOURCE, {
        type: "geojson",
        data: EMPTY_FC,
      });

      // Outer pulse ring
      map.addLayer({
        id: FIRE_PULSE,
        type: "circle",
        source: FIRE_SOURCE,
        paint: {
          "circle-radius": 14,
          "circle-color": "#ef4444",
          "circle-opacity": 0.2,
          "circle-stroke-width": 0,
        },
      });

      // Inner dot
      map.addLayer({
        id: FIRE_LAYER,
        type: "circle",
        source: FIRE_SOURCE,
        paint: {
          "circle-radius": 6,
          "circle-color": "#ef4444",
          "circle-stroke-color": "#fca5a5",
          "circle-stroke-width": 2,
          "circle-opacity": 0.9,
        },
      });

      readyRef.current = true;
    });

    // ── Hover interaction on route segments ─────────────────────────────
    let hoveredId = null;

    map.on("mousemove", ROUTE_LAYER, (e) => {
      if (!e.features?.length) return;
      map.getCanvas().style.cursor = "pointer";

      const feature = e.features[0];
      const idx = feature.properties.index;

      // Feature state for highlighting
      if (hoveredId !== null) {
        map.setFeatureState(
          { source: ROUTE_SOURCE, id: hoveredId },
          { hover: false }
        );
      }
      hoveredId = feature.id;
      map.setFeatureState(
        { source: ROUTE_SOURCE, id: hoveredId },
        { hover: true }
      );

      onSegmentHover?.(idx);

      // Popup
      const risk = feature.properties.risk_score;
      const pm25 = feature.properties.pm25_estimate;
      const dose = feature.properties.smoke_dose_ug;
      const dist = feature.properties.distance_km;

      const riskPct = (risk * 100).toFixed(0);
      const riskLabel =
        risk < 0.15 ? "Safe" :
        risk < 0.4  ? "Moderate" :
        risk < 0.7  ? "Dangerous" : "Critical";

      let html = `
        <div style="font-family:'DM Sans',system-ui,sans-serif;font-size:12px;line-height:1.5;min-width:140px">
          <div style="font-weight:600;margin-bottom:4px;font-size:13px">
            Segment #${idx}
          </div>
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
            <span style="width:8px;height:8px;border-radius:50%;background:${
              risk < 0.15 ? "#22c55e" : risk < 0.4 ? "#f59e0b" : risk < 0.7 ? "#ef4444" : "#7c2d12"
            };display:inline-block"></span>
            <span>${riskLabel} — ${riskPct}%</span>
          </div>
      `;
      if (pm25) html += `<div>PM2.5: ${pm25} µg/m³</div>`;
      if (dose) html += `<div>Dose: ${parseFloat(dose).toFixed(1)} µg</div>`;
      html += `<div style="color:#94a3b8">${dist} km</div></div>`;

      if (!popupRef.current) {
        popupRef.current = new mapboxgl.Popup({
          closeButton: false,
          closeOnClick: false,
          offset: 12,
          className: "routesafe-popup",
        });
      }

      popupRef.current
        .setLngLat(e.lngLat)
        .setHTML(html)
        .addTo(map);
    });

    map.on("mouseleave", ROUTE_LAYER, () => {
      map.getCanvas().style.cursor = "";
      if (hoveredId !== null) {
        map.setFeatureState(
          { source: ROUTE_SOURCE, id: hoveredId },
          { hover: false }
        );
        hoveredId = null;
      }
      popupRef.current?.remove();
      onSegmentHover?.(null);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
  }, []);

  // ── Update route segments layer ──────────────────────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const map = mapRef.current;

    const geojson = scoredSegments?.length
      ? segmentsToGeoJSON(scoredSegments)
      : EMPTY_FC;

    // Add feature IDs for feature-state
    geojson.features.forEach((f, i) => { f.id = i; });

    const source = map.getSource(ROUTE_SOURCE);
    if (source) source.setData(geojson);

    // Fit bounds to route
    if (scoredSegments?.length) {
      const coords = scoredSegments.flatMap((s) => [
        [s.start_lon, s.start_lat],
        [s.end_lon, s.end_lat],
      ]);
      const bounds = coords.reduce(
        (b, c) => b.extend(c),
        new mapboxgl.LngLatBounds(coords[0], coords[0])
      );
      map.fitBounds(bounds, { padding: { top: 80, bottom: 80, left: 400, right: 80 }, duration: 1200 });
    }
  }, [scoredSegments]);

  // ── Update smoke polygons layer (filtered by time) ───────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const map = mapRef.current;

    const geojson = hazardPolygons?.length
      ? polygonsToGeoJSON(hazardPolygons, selectedHours)
      : EMPTY_FC;

    const source = map.getSource(SMOKE_SOURCE);
    if (source) source.setData(geojson);
  }, [hazardPolygons, selectedHours]);

  // ── Update fire markers layer ────────────────────────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const map = mapRef.current;

    const geojson = hazardPolygons?.length
      ? firesToGeoJSON(hazardPolygons)
      : EMPTY_FC;

    const source = map.getSource(FIRE_SOURCE);
    if (source) source.setData(geojson);
  }, [hazardPolygons]);

  // ── Highlight segment from sidebar hover ─────────────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const map = mapRef.current;
    const source = map.getSource(ROUTE_SOURCE);
    if (!source) return;

    // Clear all hover states
    const data = source._data || source._options?.data;
    if (data?.features) {
      data.features.forEach((_, i) => {
        map.setFeatureState({ source: ROUTE_SOURCE, id: i }, { hover: false });
      });
    }

    // Set the hovered one
    if (hoveredSegment !== null && hoveredSegment !== undefined) {
      map.setFeatureState(
        { source: ROUTE_SOURCE, id: hoveredSegment },
        { hover: true }
      );
    }
  }, [hoveredSegment]);

  return (
    <div
      ref={containerRef}
      className="map-container"
      style={{ width: "100%", height: "100%" }}
    />
  );
}