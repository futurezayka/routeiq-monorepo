import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import { useStore } from "react-redux";
import L from "leaflet";
import "leaflet-geometryutil";
import "leaflet-polylinedecorator";
import { antPath } from "leaflet-ant-path";
import type { RootState } from "../../store";
import { selectHighlightedRouteId } from "../../selectors/ui";
import type { Route } from "../../types";

// Minimal typings for leaflet-polylinedecorator + leaflet-ant-path return values.
type AntPathLayer = L.FeatureGroup & {
  setLatLngs: (latlngs: L.LatLngExpression[]) => void;
};
type DecoratorLayer = L.Layer & {
  setPaths: (paths: L.Polyline | L.Polyline[]) => void;
};

interface Props {
  routes: Route[];
  selectedVehicleId: string | null;
}

// 3-tier polyline hierarchy (convergent fleet-dashboard convention).
// Tier-3: background — non-selected active route, blue, low opacity.
// Tier-2: traveled — slate, dashed, low opacity (covered portion of path).
// Tier-1: active-selected — teal accent, full opacity, on top.
const DEFAULT_STYLE: L.PathOptions = {
  color: "#60A5FA", weight: 3, opacity: 0.55, interactive: false,
};
const DIMMED_STYLE: L.PathOptions = {
  color: "#64748B", weight: 2, opacity: 0.40, dashArray: "6 8", interactive: false,
};
const SELECTED_STYLE: L.PathOptions = {
  color: "#22C55E", weight: 5, opacity: 1.0, interactive: false,
};
const SELECTED_TRAVELED_STYLE: L.PathOptions = {
  color: "#475569", weight: 3, opacity: 0.40, dashArray: "4 6", interactive: false,
};

// Ant-path config for reroute pulse (4.5 s before liveSlice TTL collapses it
// back to a static highlighted polyline). Amber per Linear/Mapbox warning.
const ANT_OPTS = {
  color: "#FBBF24",
  pulseColor: "#FEF3C7",
  weight: 5,
  opacity: 1.0,
  delay: 800,
  dashArray: [12, 24] as [number, number],
  hardwareAcceleration: true,
} as const;

// Arrow head styling (zinc-100, 14 px) — shown at the start of the remaining
// segment (i.e. vehicle's heading on the route).
const ARROW_HEAD_OPTS = {
  pixelSize: 12,
  polygon: false,
  pathOptions: { color: "#F4F4F5", weight: 3, opacity: 1, fill: false },
};

interface RouteEntry {
  polyline: L.Polyline;
  splitPolyline: L.Polyline | null;
  originMarker: L.Marker;
  destMarker: L.Marker;
  arrow: DecoratorLayer | null;
  antPath: AntPathLayer | null;
  vehicleId: string;
  coords: [number, number][];
  waypointsSignature: string;
  lastSplitBucket: number;
  lastStyle: string;
  lastReroute: boolean;
}

const ORIGIN_ICON = L.divIcon({
  className: "",
  html: `<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
    <rect x="2" y="2" width="12" height="12" rx="2" fill="#22C55E" stroke="white" stroke-width="2"/>
  </svg>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

const DEST_ICON = L.divIcon({
  className: "",
  html: `<svg width="20" height="28" viewBox="0 0 20 28" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M10 0C4.48 0 0 4.48 0 10c0 7.5 10 18 10 18s10-10.5 10-18C20 4.48 15.52 0 10 0z" fill="#EF4444"/>
    <circle cx="10" cy="10" r="4" fill="white"/>
  </svg>`,
  iconSize: [20, 28],
  iconAnchor: [10, 28],
});

/**
 * Snap (lat,lng) onto polyline and return progress ratio 0..1.
 * Uses leaflet-geometryutil — finds closest point ON the line, not a vertex.
 */
function snapProgress(
  map: L.Map, polyline: L.Polyline, lat: number, lng: number,
): { ratio: number; latlng: L.LatLng } | null {
  const raw = L.latLng(lat, lng);
  const latlngs = polyline.getLatLngs() as L.LatLng[];
  if (latlngs.length < 2) return null;
  const snap = L.GeometryUtil.closest(map, latlngs, raw, false);
  if (!snap) return null;
  const snapped = L.latLng(snap.lat, snap.lng);
  const ratio = L.GeometryUtil.locateOnLine(map, polyline, snapped);
  return { ratio, latlng: snapped };
}

function sig(coords: [number, number][]): string {
  if (coords.length === 0) return "0";
  const first = coords[0]!;
  const last = coords[coords.length - 1]!;
  return `${coords.length}:${first[0].toFixed(5)},${first[1].toFixed(5)}-${last[0].toFixed(5)},${last[1].toFixed(5)}`;
}

export default function ImperativeRoutes({ routes }: Props) {
  const map = useMap();
  const store = useStore<RootState>();
  const entriesRef = useRef<Map<string, RouteEntry>>(new Map());
  const layerRef = useRef<L.LayerGroup | null>(null);
  const rendererRef = useRef<L.Canvas | null>(null);
  const rafRef = useRef<number | null>(null);
  const syncRef = useRef<() => void>(() => {});
  const routesRef = useRef(routes);
  routesRef.current = routes;

  useEffect(() => {
    if (!map.getPane("routesPane")) {
      const p = map.createPane("routesPane");
      p.style.zIndex = "350";
    }
    rendererRef.current = L.canvas({ pane: "routesPane", padding: 0.5 });
    layerRef.current = L.layerGroup().addTo(map);

    const sync = () => {
      rafRef.current = null;
      const layer = layerRef.current;
      const renderer = rendererRef.current;
      if (!layer || !renderer) return;

      const state = store.getState();
      const live = state.live;
      const highlights = live.routeHighlights;            // recent reroute flash
      const positions = live.positions;
      const sel = state.ui.selectedEntity;
      const hasSelection = sel !== null;
      // Split traveled/remaining only when the user clicked a VEHICLE (the
      // intent is "track progress"). When the user clicks a ROUTE card,
      // they want the whole line highlighted, not the remainder only.
      const splitMode = sel?.type === "vehicle";
      const highlightedRouteId = selectHighlightedRouteId(state);

      const currentRoutes = routesRef.current;
      const entries = entriesRef.current;
      const seen = new Set<string>();

      for (const r of currentRoutes) {
        seen.add(r.id);
        if (!r.waypoints?.length) continue;

        const coords = r.waypoints.map(
          (wp) => [wp[1]!, wp[0]!] as [number, number],
        );
        const signature = sig(coords);
        const isSelected = r.id === highlightedRouteId;
        const isReroute = highlights[r.id] !== undefined;

        // Origin/dest markers ride the polyline endpoints, NOT raw route.origin_*
        // (raw values are user-supplied lat/lng; OSRM snaps them onto the road
        // graph, so the polyline's first/last vertex is the visually-correct
        // anchor. This kills the "green start circle floats off the line" bug.)
        const startCoord = coords[0]!;
        const endCoord = coords[coords.length - 1]!;

        let entry = entries.get(r.id);
        if (!entry) {
          const pl = L.polyline(coords, { renderer, ...DEFAULT_STYLE });
          pl.addTo(layer);
          const originM = L.marker(startCoord, { icon: ORIGIN_ICON, interactive: false }).addTo(layer);
          const destM = L.marker(endCoord, { icon: DEST_ICON, interactive: false }).addTo(layer);
          entry = {
            polyline: pl,
            splitPolyline: null,
            originMarker: originM,
            destMarker: destM,
            arrow: null,
            antPath: null,
            vehicleId: r.vehicle_id,
            coords,
            waypointsSignature: signature,
            lastSplitBucket: -1,
            lastStyle: "",
            lastReroute: false,
          };
          entries.set(r.id, entry);
        } else if (entry.waypointsSignature !== signature || isReroute) {
          entry.coords = coords;
          entry.waypointsSignature = signature;
          entry.polyline.setLatLngs(coords);
          entry.originMarker.setLatLng(startCoord);
          entry.destMarker.setLatLng(endCoord);
        }

        // Pick style based on selection state. Reroute pulse is rendered as
        // an ant-path overlay (below); the underlying base polyline takes the
        // SELECTED tier during the pulse window so it stays prominent after
        // the pulse collapses.
        let baseStyle: L.PathOptions;
        if (isReroute) {
          baseStyle = SELECTED_STYLE;
        } else if (isSelected) {
          baseStyle = SELECTED_STYLE;
        } else if (hasSelection) {
          baseStyle = DIMMED_STYLE;
        } else {
          baseStyle = DEFAULT_STYLE;
        }

        const markerOpacity = hasSelection && !isSelected ? 0.3 : 1.0;
        entry.originMarker.setOpacity(markerOpacity);
        entry.destMarker.setOpacity(markerOpacity);

        const styleKey = `${baseStyle.color}|${isSelected}|${isReroute}`;

        if (isSelected && splitMode) {
          const pos = positions[r.vehicle_id];
          if (pos && coords.length > 1) {
            // Snap vehicle position to a real point ON the polyline. Bucket
            // ratio to 1/200 (~0.5%) — re-split only when progress changes
            // visibly, so RAF doesn't churn setLatLngs every WS frame.
            const snap = snapProgress(map, entry.polyline, pos.lat, pos.lng);
            const bucket = snap ? Math.round(snap.ratio * 200) : -1;
            if (bucket !== entry.lastSplitBucket || entry.lastStyle !== styleKey) {
              entry.lastSplitBucket = bucket;
              if (snap && bucket >= 0) {
                const traveled = L.GeometryUtil.extract(
                  map, entry.polyline, 0, snap.ratio,
                );
                const remaining = L.GeometryUtil.extract(
                  map, entry.polyline, snap.ratio, 1,
                );
                // Pin the boundary vertex to the snapped point exactly so
                // marker (rendered at the same snapped LL) sits ON the join.
                if (traveled.length > 0) traveled[traveled.length - 1] = snap.latlng;
                if (remaining.length > 0) remaining[0] = snap.latlng;
                entry.polyline.setLatLngs(traveled);
                entry.polyline.setStyle(SELECTED_TRAVELED_STYLE);
                if (!entry.splitPolyline) {
                  entry.splitPolyline = L.polyline(remaining, {
                    renderer, ...baseStyle,
                  }).addTo(layer);
                } else {
                  entry.splitPolyline.setLatLngs(remaining);
                  entry.splitPolyline.setStyle(baseStyle);
                }
                entry.splitPolyline.bringToFront();
              } else {
                // No snap → don't split, just style baseline.
                if (entry.splitPolyline) {
                  entry.splitPolyline.remove();
                  entry.splitPolyline = null;
                }
                entry.polyline.setLatLngs(coords);
                entry.polyline.setStyle(baseStyle);
                entry.polyline.bringToFront();
              }
            }
          } else {
            if (entry.splitPolyline) {
              entry.splitPolyline.remove();
              entry.splitPolyline = null;
              entry.polyline.setLatLngs(coords);
            }
            entry.polyline.setStyle(baseStyle);
            entry.polyline.bringToFront();
          }
        } else if (isSelected) {
          // Route-card selection: highlight the entire polyline, no split.
          if (entry.splitPolyline) {
            entry.splitPolyline.remove();
            entry.splitPolyline = null;
            entry.lastSplitBucket = -1;
          }
          // entry.polyline may currently hold a *traveled* slice from a
          // previous vehicle-mode split — restore full coords.
          if (entry.lastStyle !== styleKey || entry.lastSplitBucket !== -2) {
            entry.polyline.setLatLngs(coords);
            entry.polyline.setStyle(baseStyle);
            entry.polyline.bringToFront();
            entry.lastSplitBucket = -2; // sentinel: "route-mode, full line"
          }
        } else {
          if (entry.splitPolyline) {
            entry.splitPolyline.remove();
            entry.splitPolyline = null;
            entry.polyline.setLatLngs(coords);
            entry.lastSplitBucket = -1;
          }
          if (entry.lastStyle !== styleKey) {
            entry.polyline.setStyle(baseStyle);
          }
        }
        entry.lastStyle = styleKey;

        // --- Ant-path overlay during reroute pulse window ---
        if (isReroute && !entry.antPath) {
          entry.antPath = antPath(coords, ANT_OPTS) as unknown as AntPathLayer;
          entry.antPath.addTo(layer);
        } else if (!isReroute && entry.antPath) {
          entry.antPath.remove();
          entry.antPath = null;
        } else if (
          isReroute && entry.antPath && entry.lastReroute
            && entry.waypointsSignature === signature
        ) {
          // no-op: pulse continues
        } else if (isReroute && entry.antPath) {
          // Coords changed mid-pulse — refresh the underlying path.
          entry.antPath.setLatLngs(coords);
        }
        entry.lastReroute = isReroute;

        // --- Heading arrow at start of remaining segment (vehicle direction).
        // Lives only on selected routes; mounts on splitPolyline so it
        // auto-tracks setLatLngs() updates from the snap-progress logic.
        const arrowTarget = isSelected ? entry.splitPolyline : null;
        const Lany = L as unknown as {
          polylineDecorator: (
            paths: L.Polyline | L.Polyline[],
            opts: { patterns: unknown[] },
          ) => DecoratorLayer;
          Symbol: { arrowHead: (opts: unknown) => unknown };
        };
        if (arrowTarget) {
          if (!entry.arrow) {
            entry.arrow = Lany.polylineDecorator(arrowTarget, {
              patterns: [{
                offset: 8,
                repeat: 0,
                symbol: Lany.Symbol.arrowHead(ARROW_HEAD_OPTS),
              }],
            });
            entry.arrow.addTo(layer);
          } else {
            entry.arrow.setPaths(arrowTarget);
          }
        } else if (entry.arrow) {
          entry.arrow.remove();
          entry.arrow = null;
        }
      }

      for (const [rid, entry] of entries) {
        if (!seen.has(rid)) {
          entry.arrow?.remove();
          entry.antPath?.remove();
          entry.polyline.remove();
          entry.splitPolyline?.remove();
          entry.originMarker.remove();
          entry.destMarker.remove();
          entries.delete(rid);
        }
      }
    };

    syncRef.current = sync;
    sync();

    let prevSelected = store.getState().ui.selectedEntity;
    let prevHighlights = store.getState().live.routeHighlights;
    let prevPositions = store.getState().live.positions;
    const unsub = store.subscribe(() => {
      const state = store.getState();
      const newSelected = state.ui.selectedEntity;
      const newHighlights = state.live.routeHighlights;
      const newPositions = state.live.positions;

      const selChanged = newSelected !== prevSelected;
      const hlChanged = newHighlights !== prevHighlights;
      const posChanged = newPositions !== prevPositions;

      prevSelected = newSelected;
      prevHighlights = newHighlights;
      prevPositions = newPositions;

      if (!selChanged && !hlChanged && !posChanged) return;
      if (posChanged && !selChanged && !hlChanged && !newSelected) return;

      if (rafRef.current !== null) return;
      rafRef.current = requestAnimationFrame(sync);
    });

    return () => {
      unsub();
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      layerRef.current?.remove();
      entriesRef.current.clear();
    };
  }, [map, store]);

  useEffect(() => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => syncRef.current());
  }, [routes]);

  return null;
}
