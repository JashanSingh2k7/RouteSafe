// src/App.jsx
import { useState, useCallback } from "react";
import Map from "./components/Map";
import SidePanel from "./components/SidePanel";
import TimeSlider from "./components/TimeSlider";
import { scoreRoute } from "./services/api";
import { fetchRoute } from "./services/directions";

export default function App() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedHours, setSelectedHours] = useState(0);
  const [hoveredSegment, setHoveredSegment] = useState(null);

  const handleSubmit = useCallback(async (params) => {
    setLoading(true);
    setError(null);
    setData(null);
    setSelectedHours(0);

    try {
      let scoreParams;

      if (params.mode === "route") {
        const route = await fetchRoute(params.origin, params.destination);
        scoreParams = {
          encodedPolyline: route.encodedPolyline,
          totalDurationMin: route.totalDurationMin,
          radiusKm: params.radiusKm,
          dayRange: params.dayRange,
          healthProfile: params.healthProfile,
        };
      } else {
        scoreParams = params;
      }

      const result = await scoreRoute(scoreParams);
      setData(result);
    } catch (err) {
      if (err.name === "AbortError") return;
      console.error("Score route failed:", err);
      setError(err.message || "Failed to score route. Check that the backend is running.");
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div className="flex h-screen w-screen bg-gray-950">
      <SidePanel
        data={data}
        loading={loading}
        error={error}
        onSubmit={handleSubmit}
        onSegmentHover={setHoveredSegment}
        hoveredSegment={hoveredSegment}
      />

      <div className="relative flex-1">
        <Map
          scoredSegments={data?.scored_segments}
          hazardPolygons={data?.hazard_polygons}
          hexGrid={data?.hex_grid}
          fires={data?.fire_hazards}
          selectedHours={selectedHours}
          hoveredSegment={hoveredSegment}
          onSegmentHover={setHoveredSegment}
        />

        <TimeSlider
          selectedHours={selectedHours}
          onChange={setSelectedHours}
          visible={!!data?.hazard_polygons?.length}
        />
      </div>
    </div>
  );
}