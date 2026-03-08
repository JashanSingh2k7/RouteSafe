// src/components/Map.jsx
import { useEffect, useRef } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MAPBOX_TOKEN, DEFAULT_CENTER, DEFAULT_ZOOM } from "../config";
import {
  segmentsToGeoJSON,
  polygonsToGeoJSON,
  riskColor,
  riskLabel,
  getRouteBounds,
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
const FIRE_SOURCE = "fire-markers";
const FIRE_LAYER = "fire-markers-circle";
const FIRE_PULSE = "fire-markers-pulse";

const EMPTY_FC = { type: "FeatureCollection", features: [] };

function extractFireMarkers(polygons) {
  const seen = new Set();
  const features = [];
  for (const poly of polygons) {
    const key = poly.source_fire;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const [latStr, lonStr] = key.split(",");
    const lat = parseFloat(latStr);
    const lon = parseFloat(lonStr);
    if (isNaN(lat) || isNaN(lon)) continue;
    features.push({
      type: "Feature",
      properties: { source_fire: key, severity: poly.severity },
      geometry: { type: "Point", coordinates: [lon, lat] },
    });
  }
  return { type: "FeatureCollection", features };
}

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
      // Smoke polygons
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

      // Route segments
      map.addSource(ROUTE_SOURCE, { type: "geojson", data: EMPTY_FC });
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

      // Fire markers
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

      readyRef.current = true;
    });

    // Hover
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
      const pm25 = feature.properties.pm25_estimate;
      const dose = feature.properties.smoke_dose_ug;
      const dist = feature.properties.distance_km;
      const color = riskColor(risk);
      const label = riskLabel(risk);
      const pct = (risk * 100).toFixed(0);

      let html = `<div style="font-family:system-ui,sans-serif;font-size:12px;line-height:1.5;min-width:140px;color:#e2e8f0">
        <div style="font-weight:600;margin-bottom:4px;font-size:13px">Segment #${idx}</div>
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
          <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block"></span>
          <span>${label} — ${pct}%</span>
        </div>`;
      if (pm25) html += `<div>PM2.5: ${pm25} µg/m³</div>`;
      if (dose) html += `<div>Dose: ${parseFloat(dose).toFixed(1)} µg</div>`;
      html += `<div style="color:#94a3b8">${dist} km</div></div>`;

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

  // Update route
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const map = mapRef.current;
    const geojson = scoredSegments?.length ? segmentsToGeoJSON(scoredSegments) : EMPTY_FC;
    geojson.features.forEach((f, i) => { f.id = i; });
    map.getSource(ROUTE_SOURCE)?.setData(geojson);
    if (scoredSegments?.length) {
      map.fitBounds(getRouteBounds(scoredSegments), {
        padding: { top: 80, bottom: 80, left: 400, right: 80 },
        duration: 1200,
      });
    }
  }, [scoredSegments]);

  // Update smoke
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const geojson = hazardPolygons?.length ? polygonsToGeoJSON(hazardPolygons, selectedHours) : EMPTY_FC;
    mapRef.current.getSource(SMOKE_SOURCE)?.setData(geojson);
  }, [hazardPolygons, selectedHours]);

  // Update fires
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return;
    const geojson = hazardPolygons?.length ? extractFireMarkers(hazardPolygons) : EMPTY_FC;
    mapRef.current.getSource(FIRE_SOURCE)?.setData(geojson);
  }, [hazardPolygons]);

  // Sidebar hover sync
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