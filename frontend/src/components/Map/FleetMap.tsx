import { memo, useMemo, useEffect, useRef } from "react";
import { useSelector, useDispatch, useStore } from "react-redux";
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  Tooltip,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import type { RootState } from "../../store";
import type { Incident, Route, Vehicle } from "../../types";
import {
  clearRouteHighlight,
  clearIncidentImpact,
  pushEvent,
} from "../../slices/liveSlice";
import { clearSelection } from "../../slices/uiSlice";
import {
  selectActiveRouteForVehicle,
  selectRouteById,
} from "../../selectors/ui";
import ImperativeVehicleMarkers from "./ImperativeVehicleMarkers";
import ImperativeRoutes from "./ImperativeRoutes";

const HIGHLIGHT_DURATION_MS = 3_000;
const IMPACT_DURATION_MS = 10_000;

const KYIV_CENTER: [number, number] = [50.45, 30.52];

// Mapbox traffic palette × type × severity. ACC=red family, CON=orange family,
// RW=amber family. WX/other fall through to severity-only mapping.
const INCIDENT_TYPE_LABELS: Record<string, string> = {
  accident: "ACC",
  congestion: "CON",
  roadwork: "RW",
  weather: "WX",
  other: "!",
};

const INCIDENT_TYPE_FULL: Record<string, string> = {
  accident: "Accident",
  congestion: "Congestion",
  roadwork: "Road Work",
  weather: "Weather",
  other: "Other",
};

const INCIDENT_TYPE_COLORS: Record<string, Record<string, string>> = {
  accident:    { low: "#FF6B6B", medium: "#FF3B30", high: "#FF0015", critical: "#981B25" },
  congestion:  { low: "#FFB366", medium: "#FF8C1A", high: "#FF6B00", critical: "#D66B00" },
  roadwork:    { low: "#FFE066", medium: "#FFD60A", high: "#FFA200", critical: "#FF7A00" },
  // weather/other inherit "moderate" severity hue.
  weather:     { low: "#7DD3FC", medium: "#38BDF8", high: "#0EA5E9", critical: "#0369A1" },
  other:       { low: "#94A3B8", medium: "#64748B", high: "#475569", critical: "#1E293B" },
};

// Per-severity badge color for sidebar / popup chips (matches map markers).
const INCIDENT_COLORS: Record<string, string> = {
  low:      "#39C66D", // Mapbox traffic low
  medium:   "#FF8C1A", // Mapbox traffic moderate
  high:     "#FF0015", // Mapbox traffic heavy
  critical: "#981B25", // Mapbox traffic severe
};

const SEVERITY_SIZE: Record<string, number> = {
  low: 22, medium: 24, high: 28, critical: 32,
};

function typeColor(type: string, severity: string): string {
  return (INCIDENT_TYPE_COLORS[type] ?? INCIDENT_TYPE_COLORS["other"])![severity]
    ?? INCIDENT_COLORS[severity] ?? "#94A3B8";
}

function createIncidentIcon(severity: string, type: string): L.DivIcon {
  const label = INCIDENT_TYPE_LABELS[type] ?? "!";
  const size = SEVERITY_SIZE[severity] ?? 24;
  const fill = typeColor(type, severity);
  return L.divIcon({
    className: "",
    html: `<div class="incident-marker incident-${severity}" style="width:${size}px;height:${size}px;background:${fill}"><span style="font-size:9px;font-weight:700;font-family:Inter,sans-serif;color:#0E0E0E;letter-spacing:0.5px">${label}</span></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2],
  });
}

function timeAgo(ts?: number | string | null): string {
  if (!ts) return "N/A";
  const ms = typeof ts === "number" ? ts : new Date(ts).getTime();
  const sec = Math.floor((Date.now() - ms) / 1000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

interface IncidentMarkerProps {
  incident: Incident;
  onResolve: (id: string) => void;
}

const IncidentMarkerItem = memo(function IncidentMarkerItem({
  incident,
  onResolve,
}: IncidentMarkerProps) {
  const icon = useMemo(
    () => createIncidentIcon(incident.severity, incident.type),
    [incident.severity, incident.type],
  );

  const color = INCIDENT_COLORS[incident.severity] ?? "#94A3B8";
  const typeLabel = INCIDENT_TYPE_FULL[incident.type] ?? incident.type;

  return (
    <Marker
      position={[incident.latitude, incident.longitude]}
      icon={icon}
      zIndexOffset={500}
    >
      <Tooltip direction="top" offset={[0, -14]} opacity={1} className="riq-tooltip">
        <div className="riq-tip__row">
          <span className="riq-tip__id">{typeLabel}</span>
          <span
            className="riq-tip__pill"
            style={{ background: `${color}20`, color }}
          >
            {incident.severity}
          </span>
        </div>
        <div className="riq-tip__row riq-tip__row--meta">
          <span>{timeAgo(incident.reported_at)}</span>
        </div>
      </Tooltip>
      <Popup>
        <div style={{ minWidth: 200, fontFamily: "Inter, sans-serif" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "#F1F5F9", textTransform: "capitalize" }}>{typeLabel}</span>
            <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600, textTransform: "uppercase", background: `${color}20`, color }}>
              {incident.severity}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "#94A3B8" }}>Reported: {timeAgo(incident.reported_at)}</div>
          <button
            onClick={() => onResolve(incident.id)}
            style={{
              marginTop: 8, width: "100%", padding: "6px 0",
              background: "transparent",
              border: "1px solid rgba(34,197,94,0.4)",
              borderRadius: 6, color: "#22C55E",
              fontSize: 12, fontWeight: 500, cursor: "pointer",
            }}
          >
            Resolve Incident
          </button>
        </div>
      </Popup>
    </Marker>
  );
});

/**
 * CameraController — flies / fitBounds on selection change.
 * No render, just a side-effect.
 */
function CameraController() {
  const map = useMap();
  const store = useStore<RootState>();
  const sel = useSelector((s: RootState) => s.ui.selectedEntity);
  const lastSelKey = useRef<string | null>(null);
  const dispatch = useDispatch();

  useEffect(() => {
    if (!sel) {
      lastSelKey.current = null;
      return;
    }
    const key = `${sel.type}:${sel.id}`;
    if (key === lastSelKey.current) return;
    lastSelKey.current = key;

    const state = store.getState();

    if (sel.type === "vehicle") {
      const route = selectActiveRouteForVehicle(state, sel.id);
      const pos = state.live.positions[sel.id];
      if (pos) {
        map.flyTo([pos.lat, pos.lng], 14, { duration: 0.8 });
      }
      if (!route) {
        dispatch(pushEvent({
          type: "info",
          message: "Vehicle has no active route",
          showToast: true,
        }));
      }
    } else if (sel.type === "route") {
      const route = selectRouteById(state, sel.id);
      if (route?.waypoints && route.waypoints.length > 1) {
        const latLngs = route.waypoints.map(
          (wp) => L.latLng(wp[1]!, wp[0]!),
        );
        const bounds = L.latLngBounds(latLngs);
        map.fitBounds(bounds, { padding: [50, 50], maxZoom: 15, animate: true, duration: 0.8 });
      }
    }
  }, [sel, map, store, dispatch]);

  return null;
}

/**
 * MapClickHandler:
 * - In picking mode (onMapClick provided + active) forwards click to caller.
 * - Otherwise, click on empty area clears selection in UI state.
 *   Clicks on markers/polylines are L.DomEvent-stopped by Leaflet so they
 *   never reach this handler — only true empty-area clicks land here.
 */
function MapClickHandler({
  onMapClick,
}: {
  onMapClick?: (lat: number, lng: number) => void;
}) {
  const map = useMap();
  const dispatch = useDispatch();
  const cbRef = useRef(onMapClick);
  cbRef.current = onMapClick;

  useEffect(() => {
    const handler = (e: L.LeafletMouseEvent) => {
      cbRef.current?.(e.latlng.lat, e.latlng.lng);
      // Independently, an empty-area click clears any current selection.
      dispatch(clearSelection());
    };
    map.on("click", handler);
    return () => { map.off("click", handler); };
  }, [map, dispatch]);

  return null;
}

interface Props {
  vehicles: Vehicle[];
  incidents: Incident[];
  routes: Route[];
  onMapClick?: (lat: number, lng: number) => void;
  onResolveIncident: (id: string) => void;
}

export default memo(function FleetMap({
  vehicles,
  incidents,
  routes,
  onMapClick,
  onResolveIncident,
}: Props) {
  const vehicleMap = useMemo(() => {
    const m: Record<string, Vehicle> = {};
    for (const v of vehicles) m[v.id] = v;
    return m;
  }, [vehicles]);

  const routeByVehicle = useMemo(() => {
    const m: Record<string, Route> = {};
    for (const r of routes) {
      if (r.status === "active") m[r.vehicle_id] = r;
    }
    return m;
  }, [routes]);

  const activeIncidents = useMemo(
    () => incidents.filter((i) => i.is_active),
    [incidents],
  );

  const routeHighlights = useSelector((s: RootState) => s.live.routeHighlights);
  const incidentImpacts = useSelector((s: RootState) => s.live.incidentImpacts);
  const dispatch = useDispatch();

  useEffect(() => {
    const timers: number[] = [];
    const now = Date.now();
    for (const h of Object.values(routeHighlights)) {
      const remaining = HIGHLIGHT_DURATION_MS - (now - h.startedAt);
      if (remaining <= 0) {
        dispatch(clearRouteHighlight(h.routeId));
      } else {
        timers.push(window.setTimeout(
          () => dispatch(clearRouteHighlight(h.routeId)),
          remaining,
        ));
      }
    }
    for (const im of Object.values(incidentImpacts)) {
      const remaining = IMPACT_DURATION_MS - (now - im.startedAt);
      if (remaining <= 0) {
        dispatch(clearIncidentImpact(im.incidentId));
      } else {
        timers.push(window.setTimeout(
          () => dispatch(clearIncidentImpact(im.incidentId)),
          remaining,
        ));
      }
    }
    return () => { for (const t of timers) window.clearTimeout(t); };
  }, [routeHighlights, incidentImpacts, dispatch]);

  return (
    <MapContainer
      center={KYIV_CENTER}
      zoom={12}
      preferCanvas={true}
      style={{ width: "100%", height: "100%", background: "#1a1a2e" }}
      zoomControl={false}
      zoomSnap={0.5}
      zoomDelta={0.5}
      wheelDebounceTime={80}
    >
      <TileLayer
        attribution='&copy; <a href="https://carto.com/">CartoDB</a>'
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        keepBuffer={3}
        updateWhenZooming={false}
        updateWhenIdle={false}
        maxNativeZoom={19}
        maxZoom={20}
      />

      <CameraController />
      <MapClickHandler onMapClick={onMapClick} />

      <ImperativeRoutes routes={routes} selectedVehicleId={null} />

      <ImperativeVehicleMarkers
        vehicleMap={vehicleMap}
        routeByVehicle={routeByVehicle}
      />

      {activeIncidents.map((inc) => (
        <IncidentMarkerItem
          key={inc.id}
          incident={inc}
          onResolve={onResolveIncident}
        />
      ))}

      {/* impact circles removed */}
    </MapContainer>
  );
});
