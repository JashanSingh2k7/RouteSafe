// src/App.jsx
import { useState, useCallback } from "react";
import Map from "./components/Map";
import SidePanel from "./components/SidePanel";
import TimeSlider from "./components/TimeSlider";
import { scoreRoute, optimizeRoute } from "./services/api";
import { fetchRoute, fetchRouteWithWaypoints } from "./services/directions";

export default function App() {
  const [data, setData] = useState(null);
  const [pendingOptimization, setPendingOptimization] = useState(null);

  const [loading, setLoading] = useState(false);
  const [optimizing, setOptimizing] = useState(false);
  const [rerouting, setRerouting] = useState(false);
  const [error, setError] = useState(null);
  const [selectedHours, setSelectedHours] = useState(0);
  const [hoveredSegment, setHoveredSegment] = useState(null);

  const [lastParams, setLastParams] = useState(null);
  const [lastRoute, setLastRoute] = useState(null);
  const [hasAppliedReroute, setHasAppliedReroute] = useState(false);

  const handleSubmit = useCallback(async (params) => {
    setLoading(true);
    setError(null);
    setData(null);
    setPendingOptimization(null);
    setSelectedHours(0);
    setLastParams(null);
    setLastRoute(null);
    setHasAppliedReroute(false);

    try {
      let scoreParams;

      if (params.mode === "route") {
        const route = await fetchRoute(params.origin, params.destination);
        setLastRoute(route);
        setLastParams(params);

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

  const handleOptimize = useCallback(async () => {
    if (!lastParams || !lastRoute) return;

    setOptimizing(true);
    setError(null);
    setPendingOptimization(null);

    try {
      const result = await optimizeRoute({
        encodedPolyline: lastRoute.encodedPolyline,
        totalDurationMin: lastRoute.totalDurationMin,
        origin: lastParams.origin,
        destination: lastParams.destination,
        radiusKm: lastParams.radiusKm,
        dayRange: lastParams.dayRange,
        healthProfile: lastParams.healthProfile,
      });

      // IMPORTANT:
      // Do NOT replace the main displayed route yet.
      // Keep the original route visible until user applies the optimized one.
      setPendingOptimization(result);
    } catch (err) {
      if (err.name === "AbortError") return;
      console.error("Optimize failed:", err);
      setError(err.message || "Failed to optimize route.");
    } finally {
      setOptimizing(false);
    }
  }, [lastParams, lastRoute]);

  const handleApplyReroute = useCallback(async () => {
    if (!pendingOptimization?.waypoints?.length || !lastParams) return;

    setRerouting(true);
    setError(null);

    try {
      const newRoute = await fetchRouteWithWaypoints(
        lastParams.origin,
        lastParams.destination,
        pendingOptimization.waypoints,
      );

      setLastRoute(newRoute);

      const result = await scoreRoute({
        encodedPolyline: newRoute.encodedPolyline,
        totalDurationMin: newRoute.totalDurationMin,
        radiusKm: lastParams.radiusKm,
        dayRange: lastParams.dayRange,
        healthProfile: lastParams.healthProfile,
      });

      // Only now replace the displayed route
      setData({
        ...result,
        briefing: "Optimized path applied.",
      });

      // Clear the pending popup/banner after apply
      setPendingOptimization(null);
      setHasAppliedReroute(true);
    } catch (err) {
      if (err.name === "AbortError") return;
      console.error("Reroute failed:", err);
      setError(err.message || "Failed to apply safer route.");
    } finally {
      setRerouting(false);
    }
  }, [pendingOptimization, lastParams]);

  const canOptimize = Boolean(
    data &&
      lastParams &&
      lastRoute &&
      !loading &&
      !rerouting &&
      !hasAppliedReroute &&
      !pendingOptimization
  );

  return (
    <div className="flex h-screen w-screen bg-gray-950">
      <SidePanel
        data={data}
        optimizationResult={pendingOptimization}
        loading={loading}
        optimizing={optimizing}
        rerouting={rerouting}
        error={error}
        onSubmit={handleSubmit}
        onOptimize={handleOptimize}
        onApplyReroute={handleApplyReroute}
        canOptimize={canOptimize}
        onSegmentHover={setHoveredSegment}
        hoveredSegment={hoveredSegment}
      />

      <div className="relative flex-1">
        <Map
          scoredSegments={data?.scored_segments}
          hazardPolygons={data?.hazard_polygons}
          hexGrid={data?.hex_grid}
          fires={data?.fire_hazards}
          waypoints={pendingOptimization?.waypoints}
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