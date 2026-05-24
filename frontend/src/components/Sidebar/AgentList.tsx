import { useState, useMemo, useCallback, useEffect, useRef, memo } from "react";
import { useSelector, useDispatch } from "react-redux";
import type { RootState } from "../../store";
import type { Vehicle, Incident, Route } from "../../types";
import { selectVehicle, selectRoute } from "../../slices/uiSlice";
import {
  selectHighlightedRouteId,
  selectHighlightedVehicleId,
} from "../../selectors/ui";

const INCIDENT_TYPE_LABELS: Record<string, string> = {
  accident: "Accident",
  congestion: "Congestion",
  roadwork: "Road Work",
  weather: "Weather",
  other: "Other",
};

// Mapbox traffic palette (mapbox/mapbox-plugins-android TrafficColor) —
// keep this synced with FleetMap's INCIDENT_COLORS.
const INCIDENT_COLORS: Record<string, string> = {
  low:      "#39C66D",
  medium:   "#FF8C1A",
  high:     "#FF0015",
  critical: "#981B25",
};

function timeAgo(ts: string | number | null | undefined): string {
  if (!ts) return "N/A";
  const ms = typeof ts === "number" ? ts : new Date(ts).getTime();
  const sec = Math.floor((Date.now() - ms) / 1000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

function timeAgoColor(ts: string | number | null | undefined): string {
  if (!ts) return "#64748B";
  const ms = typeof ts === "number" ? ts : new Date(ts).getTime();
  const sec = Math.floor((Date.now() - ms) / 1000);
  if (sec < 60) return "#94A3B8";
  if (sec < 600) return "#F59E0B";
  return "#64748B";
}

interface VehicleCardProps {
  vehicle: Vehicle;
  route?: Route;
}

const VehicleCard = memo(function VehicleCard({
  vehicle,
  route,
}: VehicleCardProps) {
  const dispatch = useDispatch();
  const isSelected = useSelector(
    (s: RootState) => selectHighlightedVehicleId(s) === vehicle.id,
  );
  const cardRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (isSelected) {
      cardRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [isSelected]);

  // Subscribe only to coarse buckets so card doesn't rerender on every WS flush.
  const speedBucket = useSelector(
    (s: RootState) => Math.round((s.live.positions[vehicle.id]?.speed ?? 0) / 5) * 5,
  );
  const isMoving = useSelector(
    (s: RootState) => (s.live.positions[vehicle.id]?.speed ?? 0) > 5,
  );
  const lastSeenBucket = useSelector((s: RootState) => {
    const ts = s.live.positions[vehicle.id]?.timestamp;
    if (typeof ts !== "number") return null;
    // Bucket by 10s — text changes "5s ago" → "15s ago" only at decade boundaries.
    return Math.floor(ts / 10_000);
  });
  const recentRecalcBumpedAt = useSelector(
    (s: RootState) => route ? s.live.recalcsByRoute[route.id]?.updatedAt ?? 0 : 0,
  );

  const lastSeen = lastSeenBucket !== null ? lastSeenBucket * 10_000 : vehicle.last_seen;
  const speed = speedBucket;
  const recalcCount = route?.recalculation_count ?? 0;
  const recentlyBumped = recentRecalcBumpedAt > 0 && (Date.now() - recentRecalcBumpedAt) < 10_000;

  const statusColor = isMoving
    ? "#22C55E"
    : vehicle.status === "active"
      ? "#F59E0B"
      : "#64748B";

  const handleClick = useCallback(
    () => dispatch(selectVehicle(vehicle.id)),
    [dispatch, vehicle.id],
  );

  return (
    <div
      ref={cardRef}
      onClick={handleClick}
      style={{
        padding: "12px 16px",
        background: isSelected ? "#1E2030" : "transparent",
        borderLeft: isSelected ? "3px solid #8B5CF6" : "3px solid transparent",
        borderBottom: "1px solid rgba(255,255,255,0.04)",
        cursor: "pointer",
        transition: "background 150ms ease, border-color 150ms ease",
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
      onMouseEnter={(e) => {
        if (!isSelected) e.currentTarget.style.background = "#1A1D27";
      }}
      onMouseLeave={(e) => {
        if (!isSelected) e.currentTarget.style.background = "transparent";
      }}
    >
      <div
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: statusColor,
          boxShadow: isMoving ? `0 0 6px ${statusColor}80` : "none",
          flexShrink: 0,
        }}
      />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex", alignItems: "center", gap: 6,
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 13,
            fontWeight: 600,
            color: "#F1F5F9",
          }}
        >
          {vehicle.license_plate}
          {recalcCount > 0 && (
            <span style={{
              padding: "1px 6px",
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 600,
              background: recentlyBumped ? "rgba(245,158,11,0.25)" : "rgba(99,102,241,0.15)",
              color: recentlyBumped ? "#F59E0B" : "#94A3B8",
              border: recentlyBumped ? "1px solid #F59E0B" : "none",
              animation: recentlyBumped ? "pulse 1s ease-in-out 3" : undefined,
              fontFamily: "Inter, sans-serif",
            }}>
              ↻{recalcCount}
            </span>
          )}
        </div>
        <div style={{ fontSize: 12, color: "#94A3B8", marginTop: 2 }}>
          {isMoving
            ? `${speed.toFixed(0)} km/h`
            : `Stopped · ${timeAgo(lastSeen)}`}
        </div>
      </div>

      {isMoving ? (
        <div
          style={{
            padding: "2px 8px",
            borderRadius: 4,
            background: "rgba(34,197,94,0.12)",
            color: "#22C55E",
            fontSize: 11,
            fontWeight: 600,
            flexShrink: 0,
          }}
        >
          {speed.toFixed(0)} km/h
        </div>
      ) : (
        <div
          style={{
            fontSize: 11,
            color: timeAgoColor(lastSeen),
            flexShrink: 0,
          }}
        >
          {timeAgo(lastSeen)}
        </div>
      )}
    </div>
  );
});

interface IncidentCardProps {
  incident: Incident;
  onViewOnMap: (lat: number, lng: number) => void;
  onResolve: (id: string) => void;
}

const IncidentCard = memo(function IncidentCard({
  incident,
  onViewOnMap,
  onResolve,
}: IncidentCardProps) {
  const color = INCIDENT_COLORS[incident.severity] ?? "#94A3B8";
  const typeLabel = INCIDENT_TYPE_LABELS[incident.type] ?? incident.type;

  const handleView = useCallback(
    () => onViewOnMap(incident.latitude, incident.longitude),
    [onViewOnMap, incident.latitude, incident.longitude],
  );
  const handleResolve = useCallback(
    () => onResolve(incident.id),
    [onResolve, incident.id],
  );

  return (
    <div
      style={{
        padding: "12px 16px",
        borderLeft: `3px solid ${color}`,
        borderBottom: "1px solid rgba(255,255,255,0.04)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "#F1F5F9",
            textTransform: "capitalize",
          }}
        >
          {typeLabel}
        </span>
        <span
          style={{
            padding: "1px 8px",
            borderRadius: 4,
            background: `${color}20`,
            color,
            fontSize: 11,
            fontWeight: 600,
            textTransform: "uppercase",
          }}
        >
          {incident.severity}
        </span>
      </div>
      <div style={{ fontSize: 12, color: "#94A3B8", marginTop: 4 }}>
        {timeAgo(incident.reported_at)}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button
          onClick={handleView}
          style={{
            flex: 1,
            padding: "5px 0",
            background: "transparent",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 6,
            color: "#94A3B8",
            fontSize: 11,
            fontWeight: 500,
            cursor: "pointer",
            transition: "all 150ms ease",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = "rgba(99,102,241,0.4)";
            e.currentTarget.style.color = "#6366F1";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)";
            e.currentTarget.style.color = "#94A3B8";
          }}
        >
          View on map
        </button>
        <button
          onClick={handleResolve}
          style={{
            flex: 1,
            padding: "5px 0",
            background: "transparent",
            border: "1px solid rgba(34,197,94,0.3)",
            borderRadius: 6,
            color: "#22C55E",
            fontSize: 11,
            fontWeight: 500,
            cursor: "pointer",
            transition: "all 150ms ease",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "rgba(34,197,94,0.1)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
          }}
        >
          Resolve
        </button>
      </div>
    </div>
  );
});

interface RouteCardProps {
  route: Route;
  vehicle?: Vehicle;
}

const RouteCard = memo(function RouteCard({
  route,
  vehicle,
}: RouteCardProps) {
  const dispatch = useDispatch();
  const isSelected = useSelector(
    (s: RootState) => selectHighlightedRouteId(s) === route.id,
  );
  const cardRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (isSelected) {
      cardRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [isSelected]);

  const handleClick = useCallback(
    () => dispatch(selectRoute(route.id)),
    [dispatch, route.id],
  );

  return (
    <div
      ref={cardRef}
      onClick={handleClick}
      style={{
        padding: "12px 16px",
        background: isSelected ? "#1E2030" : "transparent",
        borderLeft: isSelected ? "3px solid #8B5CF6" : "3px solid transparent",
        borderBottom: "1px solid rgba(255,255,255,0.04)",
        cursor: "pointer",
        transition: "background 150ms ease, border-color 150ms ease",
      }}
      onMouseEnter={(e) => {
        if (!isSelected) e.currentTarget.style.background = "#1A1D27";
      }}
      onMouseLeave={(e) => {
        if (!isSelected) e.currentTarget.style.background = "transparent";
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ color: "#6366F1", fontSize: 12, fontWeight: 600 }}>RT</span>
          <span
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 13,
              fontWeight: 600,
              color: "#F1F5F9",
            }}
          >
            {vehicle?.license_plate ?? route.vehicle_id.slice(0, 8)}
          </span>
        </div>
        <span style={{ fontSize: 12, color: "#94A3B8" }}>
          {route.distance_km?.toFixed(1) ?? "?"} km
        </span>
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: 4,
        }}
      >
        <span style={{ fontSize: 12, color: "#94A3B8" }}>
          ETA: {route.eta_minutes ?? "?"} min
        </span>
        {route.recalculation_count > 0 && (
          <span
            style={{
              padding: "1px 6px",
              borderRadius: 4,
              border: "1px solid rgba(245,158,11,0.3)",
              color: "#F59E0B",
              fontSize: 10,
              fontWeight: 600,
            }}
          >
            {route.recalculation_count}x rerouted
          </span>
        )}
      </div>
      <div
        style={{
          marginTop: 8,
          height: 3,
          borderRadius: 2,
          background: "rgba(255,255,255,0.06)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            borderRadius: 2,
            background: "#6366F1",
            width: route.eta_minutes ? "40%" : "0%",
            transition: "width 300ms ease",
          }}
        />
      </div>
    </div>
  );
});

interface TabDef {
  id: string;
  label: string;
  count: number;
}

interface Props {
  vehicles: Vehicle[];
  incidents: Incident[];
  routes: Route[];
  onViewIncident: (lat: number, lng: number) => void;
  onResolveIncident: (id: string) => void;
}

export default memo(function AgentList({
  vehicles,
  incidents,
  routes,
  onViewIncident,
  onResolveIncident,
}: Props) {
  const [activeTab, setActiveTab] = useState("vehicles");
  const [search, setSearch] = useState("");

  const routeByVehicle = useMemo(() => {
    const m: Record<string, Route> = {};
    for (const r of routes) {
      if (r.status === "active") m[r.vehicle_id] = r;
    }
    return m;
  }, [routes]);

  const sorted = useMemo(() => {
    const order = { active: 0, idle: 1, offline: 2 };
    let list = [...vehicles].sort(
      (a, b) =>
        (order[a.status as keyof typeof order] ?? 3) -
        (order[b.status as keyof typeof order] ?? 3),
    );
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((v) => v.license_plate.toLowerCase().includes(q));
    }
    return list;
  }, [vehicles, search]);

  const activeIncidents = useMemo(
    () => incidents.filter((i) => i.is_active),
    [incidents],
  );

  const vehicleMap = useMemo(() => {
    const m: Record<string, Vehicle> = {};
    for (const v of vehicles) m[v.id] = v;
    return m;
  }, [vehicles]);

  const tabs: TabDef[] = [
    { id: "vehicles", label: "Fleet", count: vehicles.length },
    { id: "incidents", label: "Incidents", count: activeIncidents.length },
    { id: "routes", label: "Routes", count: routes.length },
  ];

  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: "#0F1117",
        fontFamily: "Inter, sans-serif",
      }}
    >
      <div
        style={{
          display: "flex",
          gap: 4,
          padding: "12px 16px",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: "6px 14px",
              borderRadius: 6,
              border: "none",
              background: activeTab === tab.id ? "#6366F1" : "transparent",
              color: activeTab === tab.id ? "#fff" : "#94A3B8",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 150ms ease",
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            {tab.label}
            <span
              style={{
                marginLeft: 4,
                padding: "1px 6px",
                borderRadius: 10,
                background:
                  activeTab === tab.id
                    ? "rgba(255,255,255,0.2)"
                    : "#242736",
                fontSize: 11,
              }}
            >
              {tab.count}
            </span>
          </button>
        ))}
      </div>

      {activeTab === "vehicles" && (
        <div style={{ padding: "12px 16px 4px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              background: "#1A1D27",
              borderRadius: 8,
              border: "1px solid rgba(255,255,255,0.06)",
              padding: "0 12px",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748B" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input
              type="text"
              placeholder="Search by plate..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                flex: 1,
                background: "transparent",
                border: "none",
                outline: "none",
                color: "#F1F5F9",
                fontSize: 13,
                padding: "8px 0",
                fontFamily: "Inter, sans-serif",
              }}
            />
          </div>
        </div>
      )}

      <div style={{ flex: 1, overflow: "auto" }}>
        {activeTab === "vehicles" &&
          sorted.map((v) => (
            <VehicleCard
              key={v.id}
              vehicle={v}
              route={routeByVehicle[v.id]}
            />
          ))}

        {activeTab === "incidents" &&
          activeIncidents.map((inc) => (
            <IncidentCard
              key={inc.id}
              incident={inc}
              onViewOnMap={onViewIncident}
              onResolve={onResolveIncident}
            />
          ))}

        {activeTab === "routes" &&
          routes.map((r) => (
            <RouteCard
              key={r.id}
              route={r}
              vehicle={vehicleMap[r.vehicle_id]}
            />
          ))}
      </div>
    </div>
  );
});
