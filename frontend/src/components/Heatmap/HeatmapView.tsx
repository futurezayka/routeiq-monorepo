import { useEffect } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet.heat";
import type { HeatmapPoint } from "../../types";

const KYIV_CENTER: [number, number] = [50.4501, 30.5234];

function HeatLayer({ points }: { points: HeatmapPoint[] }) {
  const map = useMap();

  useEffect(() => {
    if (!points.length) return;

    const data: [number, number, number][] = points.map((p) => [
      p.lat,
      p.lng,
      Math.max(0.1, Math.min(1, p.congestion_level)),
    ]);

    const layer = (L as typeof L & { heatLayer: (data: [number, number, number][], opts: object) => L.Layer })
      .heatLayer(data, {
        radius: 25,
        blur: 18,
        maxZoom: 14,
        gradient: {
          0.0: "#22c55e",
          0.4: "#facc15",
          0.7: "#f97316",
          1.0: "#ef4444",
        },
      });
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [points, map]);

  return null;
}

function InvalidateOnMount() {
  const map = useMap();
  useEffect(() => {
    setTimeout(() => map.invalidateSize(), 50);
  }, [map]);
  return null;
}

export default function HeatmapView({
  points,
  fullscreen = false,
}: {
  points: HeatmapPoint[];
  fullscreen?: boolean;
}) {
  return (
    <MapContainer
      center={KYIV_CENTER}
      zoom={11}
      style={{
        height: fullscreen ? "100%" : 360,
        borderRadius: fullscreen ? 0 : 8,
        background: "#1a1a2e",
      }}
      scrollWheelZoom
      dragging
    >
      <TileLayer
        attribution="&copy; OpenStreetMap"
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
      />
      <HeatLayer points={points} />
      {fullscreen && <InvalidateOnMount />}
    </MapContainer>
  );
}
