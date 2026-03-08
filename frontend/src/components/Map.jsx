// src/components/Map.jsx
import { useEffect, useRef } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MAPBOX_TOKEN, DEFAULT_CENTER, DEFAULT_ZOOM } from "../config";
import {
  segmentsToGeoJSON,
  polygonsToGeoJSON,
  firesToGeoJSON,
  hexGridToGeoJSON,
  riskColor,
  riskLabel,
  getFullBounds,
} from "../services/mapUtils";

// Risk score → color ramp for Mapbox interpolation
const SEGMENT_COLOR_STOPS = [
  0.00, "#555555",
  0.15, "#84cc16",
  0.30, "#f59e0b",
  0.45, "#f97316",
  0.60, "#ef4444",
  0.80, "#dc2626",
  1.00, "#7c2d12",
];

// Layer IDs
const ROUTE_SOURCE = "route-segments";
const ROUTE_LAYER = "route-segments-line";
const ROUTE_CASING = "route-segments-casing";
const SMOKE_SOURCE = "smoke-polygons";
const SMOKE_LAYER = "smoke-polygons-fill";
const SMOKE_OUTLINE = "smoke-polygons-outline";
const HEX_SOURCE = "hex-grid";
const HEX_FILL = "hex-grid-fill";
const HEX_OUTLINE = "hex-grid-outline";
const FIRE_SOURCE = "fire-markers";
const FIRE_LAYER = "fire-markers-circle";
const FIRE_PULSE = "fire-markers-pulse";
const WAYPOINT_SOURCE = "waypoint-markers";
const WAYPOINT_LAYER = "waypoint-markers-circle";
const WAYPOINT_LABEL = "waypoint-markers-label";
const SNOW_SOURCE = "snow-grid";
const SNOW_FILL = "snow-grid-fill";
const SNOW_OUTLINE = "snow-grid-outline";

const EMPTY_FC = { type: "FeatureCollection", features: [] };

function waypointsToGeoJSON(waypoints) {
  if (!waypoints?.length) return EMPTY_FC;
  return {
    type: "FeatureCollection",
    features: waypoints.map((wp, i) => ({
      type: "Feature",
      properties: { index: i + 1, label: `W${i + 1}` },
      geometry: {
        type: "Point",
        coordinates: [wp.lon, wp.lat],
      },
    })),
  };
}

export default function Map({
  scoredSegments,
  hazardPolygons,
  hexGrid,
  snowGrid,
  fires,
  waypoints,
  hazardView,
  selectedHours,
  hoveredSegment,
  onSegmentHover,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);
  const readyRef = useRef(false);

  // Initialize map
  useEffect(() => {
    if (mapRef.current) return;
    mapboxgl.accessToken = MAPBOX_TOKEN;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      pitch: 0,
      antialias: true,
    });

    map.addControl(new mapboxgl.NavigationControl(), "bottom-right");
    map.addControl(new mapboxgl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("load", () => {
      // ── Smoke polygons ─────────────────────────────────────────────
      map.addSource(SMOKE_SOURCE, { type: "geojson", data: EMPTY_FC });
      map.addLayer({
        id: SMOKE_LAYER,
        type: "fill",
        source: SMOKE_SOURCE,
        paint: {
          "fill-color": [
            "match", ["get", "severity"],
            "low", "rgba(156,163,175,0.12)",
            "moderate", "rgba(156,163,175,0.25)",
            "high", "rgba(107,114,128,0.38)",
            "critical", "rgba(75,85,99,0.50)",
            "rgba(156,163,175,0.18)",
          ],
          "fill-opacity": ["get", "opacity"],
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

      // ── H3 hex grid ────────────────────────────────────────────────
      map.addSource(HEX_SOURCE, { type: "geojson", data: EMPTY_FC });
      map.addLayer({
        id: HEX_FILL,
        type: "fill",
        source: HEX_SOURCE,
        paint: {
          "fill-color": [
            "interpolate", ["linear"], ["get", "severity"],
            0,    "rgba(60,60,60,0.0)",
            0.15, "rgba(80,80,80,0.15)",
            0.35, "rgba(120,120,120,0.25)",
            0.6,  "rgba(249,115,22,0.35)",
            1.0,  "rgba(239,68,68,0.50)",
          ],
          "fill-opacity": 1,
        },
      });
      map.addLayer({
        id: HEX_OUTLINE,
        type: "line",
        source: HEX_SOURCE,
        paint: {
          "line-color": [
            "interpolate", ["linear"], ["get", "severity"],
            0,    "rgba(60,60,60,0.0)",
            0.15, "rgba(100,100,100,0.1)",
            0.35, "rgba(140,140,140,0.15)",
            0.6,  "rgba(249,115,22,0.25)",
            1.0,  "rgba(239,68,68,0.35)",
          ],
          "line-width": 0.5,
        },
      });

      // ── Route segments ─────────────────────────────────────────────
      map.addSource(ROUTE_SOURCE, { type: "geojson", data: EMPTY_FC });

      // ── Snow/ice hex grid (blue) ───────────────────────────────────
      map.addSource(SNOW_SOURCE, { type: "geojson", data: EMPTY_FC });
      map.addLayer({
        id: SNOW_FILL,
        type: "fill",
        source: SNOW_SOURCE,
        paint: {
          "fill-color": [
            "interpolate", ["linear"], ["get", "severity"],
            0,    "rgba(59,130,246,0.0)",
            0.15, "rgba(147,197,253,0.25)",
            0.35, "rgba(96,165,250,0.35)",
            0.6,  "rgba(59,130,246,0.50)",
            0.85, "rgba(29,78,216,0.65)",
            1.0,  "rgba(30,58,138,0.80)",
          ],
          "fill-opacity": 1,
        },
      });
      map.addLayer({
        id: SNOW_OUTLINE,
        type: "line",
        source: SNOW_SOURCE,
        paint: {
          "line-color": [
            "interpolate", ["linear"], ["get", "severity"],
            0,    "rgba(59,130,246,0.0)",
            0.15, "rgba(147,197,253,0.1)",
            0.35, "rgba(96,165,250,0.15)",
            0.6,  "rgba(59,130,246,0.25)",
            1.0,  "rgba(30,58,138,0.35)",
          ],
          "line-width": 0.5,
        },
      });
      map.addLayer({
        id: ROUTE_CASING,
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#0f172a", "line-width": 7, "line-opacity": 0.7 },
      });
      map.addLayer({
        id: ROUTE_LAYER,
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": ["interpolate", ["linear"], ["get", "risk_score"], ...SEGMENT_COLOR_STOPS],
          "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 6, 4],
          "line-opacity": 1,
        },
      });

      // ── Fire markers ───────────────────────────────────────────────
      map.addSource(FIRE_SOURCE, { type: "geojson", data: EMPTY_FC });
      map.addLayer({
        id: FIRE_PULSE,
        type: "circle",
        source: FIRE_SOURCE,
        paint: { "circle-radius": 14, "circle-color": "#ef4444", "circle-opacity": 0.2 },
      });
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

      // ── Waypoint markers (L4 avoidance points) ────────────────────
      map.addSource(WAYPOINT_SOURCE, { type: "geojson", data: EMPTY_FC });
      map.addLayer({
        id: WAYPOINT_LAYER,
        type: "circle",
        source: WAYPOINT_SOURCE,
        paint: {
          "circle-radius": 7,
          "circle-color": "#10b981",
          "circle-stroke-color": "#6ee7b7",
          "circle-stroke-width": 2,
          "circle-opacity": 0.9,
        },
      });
      map.addLayer({
        id: WAYPOINT_LABEL,
        type: "symbol",
        source: WAYPOINT_SOURCE,
        layout: {
          "text-field": ["get", "label"],
          "text-size": 10,
          "text-offset": [0, -1.5],
          "text-anchor": "bottom",
          "text-font": ["DIN Pro Medium", "Arial Unicode MS Regular"],
        },
        paint: {
          "text-color": "#6ee7b7",
          "text-halo-color": "#0f172a",
          "text-halo-width": 1.5,
        },
      });

      readyRef.current = true;
    });

    // ── Hover interaction ──────────────────────────────────────────────
    let hoveredId = null;
    map.on("mousemove", ROUTE_LAYER, (e) => {
      if (!e.features?.length) return;
      map.getCanvas().style.cursor = "pointer";
      const feature = e.features[0];
      const idx = feature.properties.index;

      if (hoveredId !== null) {
        map.setFeatureState({ source: ROUTE_SOURCE, id: hoveredId }, { hover: false });
      }
      hoveredId = feature.id;
      map.setFeatureState({ source: ROUTE_SOURCE, id: hoveredId }, { hover: true });
      onSegmentHover?.(idx);

      const risk = feature.properties.risk_score;
      const aqi = feature.properties.aqi_estimate;
      const dist = feature.properties.distance_km;
      const time = feature.properties.cumulative_time_min;
      const color = riskColor(risk);
      const label = riskLabel(risk);
      const pct = (risk * 100).toFixed(0);

      let html = `<div style="font-family:system-ui,sans-serif;font-size:12px;line-height:1.5;min-width:140px;color:#e2e8f0">
        <div style="font-weight:600;margin-bottom:4px;font-size:13px">Segment #${idx}</div>
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
          <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block"></span>
          <span>${label} — ${pct}%</span>
        </div>`;
      if (aqi) html += `<div>AQI ~${aqi}</div>`;
      html += `<div style="color:#94a3b8">${dist} km · t+${Math.round(time || 0)}m</div></div>`;

      if (!popupRef.current) {
        popupRef.current = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, offset: 12 });
      }
      popupRef.current.setLngLat(e.lngLat).setHTML(html).addTo(map);
    });

    map.on("mouseleave", ROUTE_LAYER, () => {
      map.getCanvas().style.cursor = "";
      if (hoveredId !== null) {
        map.setFeatureState({ source: ROUTE_SOURCE, id: hoveredId }, { hover: false });
        hoveredId = null;
      }
      popupRef.current?.remove();
      onSegmentHover?.(null);
    });

    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; readyRef.current = false; };
  }, []);

  // ── Update route + fit bounds to include fires ───────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const map = mapRef.current;
    const geojson = scoredSegments?.length ? segmentsToGeoJSON(scoredSegments) : EMPTY_FC;
    geojson.features.forEach((f, i) => { f.id = i; });
    map.getSource(ROUTE_SOURCE)?.setData(geojson);

    if (scoredSegments?.length) {
      const bounds = getFullBounds(scoredSegments, fires, waypoints);
      if (bounds) {
        map.fitBounds(bounds, {
          padding: { top: 80, bottom: 80, left: 400, right: 80 },
          duration: 1200,
        });
      }
    }
  }, [scoredSegments, fires, waypoints]);

  // ── Update smoke polygons ────────────────────────────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const geojson = hazardPolygons?.length ? polygonsToGeoJSON(hazardPolygons, selectedHours) : EMPTY_FC;
    mapRef.current.getSource(SMOKE_SOURCE)?.setData(geojson);
  }, [hazardPolygons, selectedHours]);

  // ── Update H3 hex grid ───────────────────────────────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    if (!hexGrid || Object.keys(hexGrid).length === 0) return;

    hexGridToGeoJSON(hexGrid).then((geojson) => {
      mapRef.current?.getSource(HEX_SOURCE)?.setData(geojson);
    });
  }, [hexGrid]);

  // ── Update fire markers ──────────────────────────────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const geojson = fires?.length ? firesToGeoJSON(fires) : EMPTY_FC;
    mapRef.current.getSource(FIRE_SOURCE)?.setData(geojson);
  }, [fires]);

  // ── Update snow/ice hex grid (blue) ──────────────────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    if (!snowGrid || Object.keys(snowGrid).length === 0) {
      mapRef.current.getSource(SNOW_SOURCE)?.setData(EMPTY_FC);
      return;
    }

    hexGridToGeoJSON(snowGrid).then((geojson) => {
      mapRef.current?.getSource(SNOW_SOURCE)?.setData(geojson);
    });
  }, [snowGrid]);

  // ── Toggle visibility: fire vs snow layers ───────────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const map = mapRef.current;
    const showFire = hazardView === "fire" || hazardView === "all";
    const showSnow = hazardView === "snow" || hazardView === "all";

    // Fire/smoke layers
    [HEX_FILL, HEX_OUTLINE, SMOKE_LAYER, SMOKE_OUTLINE, FIRE_LAYER, FIRE_PULSE].forEach((id) => {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", showFire ? "visible" : "none");
    });

    // Snow layers
    [SNOW_FILL, SNOW_OUTLINE].forEach((id) => {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", showSnow ? "visible" : "none");
    });
  }, [hazardView]);

  // ── Update waypoint markers (L4 avoidance points) ────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const geojson = waypointsToGeoJSON(waypoints);
    mapRef.current.getSource(WAYPOINT_SOURCE)?.setData(geojson);
  }, [waypoints]);

  // ── Sidebar hover sync ───────────────────────────────────────────────────
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const map = mapRef.current;
    const source = map.getSource(ROUTE_SOURCE);
    if (!source) return;
    const data = source._data || source._options?.data;
    if (data?.features) {
      data.features.forEach((_, i) => {
        map.setFeatureState({ source: ROUTE_SOURCE, id: i }, { hover: false });
      });
    }
    if (hoveredSegment !== null && hoveredSegment !== undefined) {
      map.setFeatureState({ source: ROUTE_SOURCE, id: hoveredSegment }, { hover: true });
    }
  }, [hoveredSegment]);

  return <div ref={containerRef} className="w-full h-full" />;
}