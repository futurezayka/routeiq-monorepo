import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import { useStore } from "react-redux";
import L from "leaflet";
import "leaflet-geometryutil";
import type { RootState } from "../../store";
import { selectHighlightedVehicleId } from "../../selectors/ui";
import { selectVehicle } from "../../slices/uiSlice";
import type { Vehicle, Route } from "../../types";

interface Props {
  vehicleMap: Record<string, Vehicle>;
  routeByVehicle: Record<string, Route>;
}

// Mapbox traffic palette (mapbox/mapbox-plugins-android TrafficPlugin.TrafficColor).
// Body + darker "casing" companion — drives the 2-fill boosted-marker pattern.
const STATUS_COLOR = {
  driving:  { fill: "#39C66D", stroke: "#059441" }, // traffic low (free flow)
  idle:     { fill: "#FFD60A", stroke: "#B8A000" }, // iOS system amber
  offline:  { fill: "#52525B", stroke: "#27272A" }, // zinc-600 / zinc-800
};
const HALO_COLOR = "#22C55E"; // green-500 selection accent

const SNAP_TOLERANCE_M = 80;  // generous for 5 s GPS pings on a snapped OSRM line

function pickStatus(v: Vehicle | undefined, speedKmh: number, lastSeenTs: number | undefined):
  keyof typeof STATUS_COLOR
{
  if (v && v.status === "offline") return "offline";
  if (lastSeenTs && Date.now() - lastSeenTs > 5 * 60_000) return "offline";
  if (speedKmh > 5) return "driving";
  return "idle";
}

interface VehicleVisual {
  outer: L.CircleMarker;
  inner: L.CircleMarker;
}

function tooltipHtml(v: Vehicle | undefined, route: Route | undefined, speed: number, vid: string): string {
  const isMoving = speed > 5;
  const plate = v?.license_plate ?? vid.slice(0, 8);
  const statusColor = isMoving ? STATUS_COLOR.driving.fill : STATUS_COLOR.idle.fill;
  const statusBg = isMoving ? "rgba(57,198,109,0.15)" : "rgba(255,214,10,0.15)";
  const statusLabel = isMoving ? "moving" : "stopped";
  const etaPart = route?.eta_minutes != null ? ` · ETA <span class="riq-tip__num">${route.eta_minutes}m</span>` : "";
  return `
    <div class="riq-tip__row">
      <span class="riq-tip__id">${plate}</span>
      <span class="riq-tip__pill" style="background:${statusBg};color:${statusColor}">${statusLabel}</span>
    </div>
    <div class="riq-tip__row riq-tip__row--meta">
      <span class="riq-tip__num">${speed.toFixed(0)} km/h</span>${etaPart}
    </div>`;
}

function popupHtml(v: Vehicle | undefined, route: Route | undefined, speed: number, vid: string): string {
  const isMoving = speed > 5;
  const plate = v?.license_plate ?? vid.slice(0, 8);
  const statusBg = isMoving ? "rgba(57,198,109,0.15)" : "rgba(255,214,10,0.15)";
  const statusColor = isMoving ? STATUS_COLOR.driving.fill : STATUS_COLOR.idle.fill;
  const statusLabel = isMoving ? "moving" : "stopped";
  const routeBlock = route
    ? `<div style="font-size:12px;color:#94A3B8;margin-top:4px;border-top:1px solid rgba(255,255,255,0.06);padding-top:4px">
         <div>Distance: ${route.distance_km?.toFixed(1) ?? "?"} km</div>
         <div>ETA: ${route.eta_minutes ?? "?"} min</div>
         ${route.recalculation_count > 0 ? `<div style="color:#F59E0B">Rerouted ${route.recalculation_count}x</div>` : ""}
       </div>`
    : "";
  return `<div style="min-width:200px;font-family:Inter,sans-serif">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <span style="font-family:JetBrains Mono,monospace;font-weight:600;font-size:13px;color:#F1F5F9">${plate}</span>
      <span style="padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;background:${statusBg};color:${statusColor}">${statusLabel}</span>
    </div>
    <div style="font-size:12px;color:#94A3B8">Speed: ${speed.toFixed(0)} km/h</div>
    ${routeBlock}
    <button data-assign-route="${vid}" style="margin-top:8px;width:100%;padding:6px 0;background:#6366F1;color:white;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;font-family:Inter,sans-serif">Assign Route</button>
  </div>`;
}

export default function ImperativeVehicleMarkers({
  vehicleMap,
  routeByVehicle,
}: Props) {
  const map = useMap();
  const store = useStore<RootState>();
  const markersRef = useRef<Map<string, VehicleVisual>>(new Map());
  const layerRef = useRef<L.LayerGroup | null>(null);
  const rendererRef = useRef<L.Canvas | null>(null);
  const haloRef = useRef<L.CircleMarker | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastPosTimestampRef = useRef<Map<string, number>>(new Map());
  const lastStyleRef = useRef<Map<string, string>>(new Map());
  const lastSelectedRef = useRef<string | null>(null);
  const lastZoomRef = useRef<number>(0);
  const openPopupVidRef = useRef<string | null>(null);

  const vehicleMapRef = useRef(vehicleMap);
  vehicleMapRef.current = vehicleMap;
  const routeByVehicleRef = useRef(routeByVehicle);
  routeByVehicleRef.current = routeByVehicle;

  useEffect(() => {
    if (!map.getPane("vehiclesPane")) {
      const p = map.createPane("vehiclesPane");
      p.style.zIndex = "450";
    }
    if (!map.getPane("haloPane")) {
      const p = map.createPane("haloPane");
      p.style.zIndex = "445"; // below vehicles, above routes
    }
    rendererRef.current = L.canvas({ pane: "vehiclesPane", padding: 0.5 });
    layerRef.current = L.layerGroup().addTo(map);

    // Single shared selection halo — moved between vehicles, no per-vehicle
    // halo layer churn. Hidden by default.
    const haloRenderer = L.canvas({ pane: "haloPane", padding: 0.5 });
    haloRef.current = L.circleMarker([0, 0], {
      renderer: haloRenderer,
      radius: 22,
      stroke: true,
      color: HALO_COLOR,
      weight: 2,
      fillColor: HALO_COLOR,
      fillOpacity: 0,
      opacity: 0,
      interactive: false,
      pane: "haloPane",
    }).addTo(map);

    let zooming = false;
    map.on("zoomanim", () => { zooming = true; });
    map.on("zoomend", () => { zooming = false; });

    // Sizes: 8 px @ z≤11 → 14 px @ z≥16 (Mapbox-style overlay scaling).
    const sizeForZoom = (z: number) =>
      z >= 16 ? 14 : z >= 14 ? 12 : z >= 12 ? 10 : z >= 11 ? 8 : 6;

    // Snap raw GPS to the vehicle's assigned route polyline. Bounded by
    // tolerance so a vehicle that genuinely went off-route stays at raw GPS.
    const snapToRoute = (
      route: Route | undefined,
      raw: L.LatLng,
    ): L.LatLng => {
      if (!route?.waypoints || route.waypoints.length < 2) return raw;
      const wps = route.waypoints.map(
        (wp) => L.latLng(wp[1]!, wp[0]!),
      );
      const snap = L.GeometryUtil.closest(map, wps, raw, false);
      if (!snap) return raw;
      const dist = map.distance(raw, L.latLng(snap.lat, snap.lng));
      if (dist > SNAP_TOLERANCE_M) return raw;
      return L.latLng(snap.lat, snap.lng);
    };

    const sync = () => {
      rafRef.current = null;
      const positions = store.getState().live.positions;
      const layer = layerRef.current;
      const renderer = rendererRef.current;
      const halo = haloRef.current;
      if (!layer || !renderer || !halo) return;

      const existing = markersRef.current;
      const seen = new Set<string>();
      const highlightedVehicle = selectHighlightedVehicleId(store.getState());
      const zoom = map.getZoom();
      const zoomChanged = zoom !== lastZoomRef.current;
      lastZoomRef.current = zoom;
      const baseSize = sizeForZoom(zoom);

      let haloLatLng: L.LatLng | null = null;

      for (const [vid, pos] of Object.entries(positions)) {
        seen.add(vid);
        const v = vehicleMapRef.current[vid];
        const route = routeByVehicleRef.current[vid];

        const status = pickStatus(v, pos.speed ?? 0, pos.timestamp);
        const c = STATUS_COLOR[status];
        const isSelected = vid === highlightedVehicle;
        const outerR = baseSize + (isSelected ? 1 : 0);
        const innerR = Math.max(2, outerR - 2);

        const lastTs = lastPosTimestampRef.current.get(vid);
        const ts = typeof pos.timestamp === "number" ? pos.timestamp : 0;
        const positionChanged = lastTs !== ts;

        // Snap raw GPS to route polyline so marker sits ON the line.
        const raw = L.latLng(pos.lat, pos.lng);
        const snapped = snapToRoute(route, raw);

        let visual = existing.get(vid);
        if (!visual) {
          // Boosted 2-fill pattern: outer = "stroke proxy" (darker casing),
          // inner = body. Two fills outperform one stroked fill on canvas by
          // ~50% (oliverheilig/leaflet-marker-booster). Inner takes events.
          const outer = L.circleMarker(snapped, {
            renderer,
            radius: outerR,
            stroke: false,
            fillColor: c.stroke,
            fillOpacity: 1,
            interactive: false,
            pane: "vehiclesPane",
          });
          const inner = L.circleMarker(snapped, {
            renderer,
            radius: innerR,
            stroke: false,
            fillColor: c.fill,
            fillOpacity: 1,
            interactive: true,
            bubblingMouseEvents: false,
            pane: "vehiclesPane",
          });
          // Hover tooltip: terse triage info (plate + status + speed/ETA).
          // Bound as a function so it re-renders on every mouseover with
          // fresh speed/ETA from the store.
          inner.bindTooltip(
            () => {
              const curV = vehicleMapRef.current[vid];
              const curR = routeByVehicleRef.current[vid];
              const cur = store.getState().live.positions[vid];
              const sp = cur?.speed ?? 0;
              return tooltipHtml(curV, curR, sp, vid);
            },
            {
              direction: "top",
              offset: [0, -8],
              opacity: 1,
              sticky: false,
              className: "riq-tooltip",
              permanent: false,
            },
          );
          // Click popup: full action surface (driver, route, Assign button).
          inner.on("click", (e) => {
            L.DomEvent.stopPropagation(e.originalEvent);
            L.DomEvent.preventDefault(e.originalEvent);
            inner.closeTooltip(); // hide hover when popup opens
            store.dispatch(selectVehicle(vid));
            const prevVid = openPopupVidRef.current;
            if (prevVid && prevVid !== vid) {
              const prev = markersRef.current.get(prevVid);
              if (prev) {
                prev.inner.closePopup();
                prev.inner.unbindPopup();
              }
            }
            const curV = vehicleMapRef.current[vid];
            const curR = routeByVehicleRef.current[vid];
            const cur = store.getState().live.positions[vid];
            const sp = cur?.speed ?? 0;
            inner
              .bindPopup(popupHtml(curV, curR, sp, vid), {
                closeButton: true,
                autoClose: false,
              })
              .openPopup();
            openPopupVidRef.current = vid;
          });
          outer.addTo(layer);
          inner.addTo(layer);
          visual = { outer, inner };
          existing.set(vid, visual);
        } else {
          if (positionChanged) {
            visual.outer.setLatLng(snapped);
            visual.inner.setLatLng(snapped);
          }
          const styleKey = `${c.fill}|${c.stroke}|${outerR}|${innerR}`;
          if (lastStyleRef.current.get(vid) !== styleKey || zoomChanged) {
            visual.outer.setStyle({ fillColor: c.stroke });
            visual.outer.setRadius(outerR);
            visual.inner.setStyle({ fillColor: c.fill });
            visual.inner.setRadius(innerR);
            lastStyleRef.current.set(vid, styleKey);
          }
        }

        if (isSelected) {
          haloLatLng = snapped;
          if (lastSelectedRef.current !== highlightedVehicle) {
            visual.outer.bringToFront();
            visual.inner.bringToFront();
          }
        }
        if (positionChanged) lastPosTimestampRef.current.set(vid, ts);
      }

      // Position the shared halo; hide if nothing selected.
      if (haloLatLng) {
        halo.setLatLng(haloLatLng);
        halo.setStyle({ opacity: 0.9, fillOpacity: 0.15 });
        halo.setRadius(baseSize + 12);
      } else {
        halo.setStyle({ opacity: 0, fillOpacity: 0 });
      }
      lastSelectedRef.current = highlightedVehicle;

      for (const [vid, visual] of existing) {
        if (!seen.has(vid)) {
          visual.inner.closePopup();
          visual.inner.unbindPopup();
          if (openPopupVidRef.current === vid) {
            openPopupVidRef.current = null;
          }
          visual.outer.remove();
          visual.inner.remove();
          existing.delete(vid);
          lastPosTimestampRef.current.delete(vid);
          lastStyleRef.current.delete(vid);
        }
      }
    };

    sync();
    const onZoomEnd = () => {
      if (rafRef.current !== null) return;
      rafRef.current = requestAnimationFrame(sync);
    };
    map.on("zoomend", onZoomEnd);
    let prevPositions = store.getState().live.positions;
    let prevSelected = store.getState().ui.selectedEntity;
    const unsub = store.subscribe(() => {
      const state = store.getState();
      const newPositions = state.live.positions;
      const newSelected = state.ui.selectedEntity;
      const selectionChanged = newSelected !== prevSelected;
      if (newPositions === prevPositions && !selectionChanged) return;
      prevPositions = newPositions;
      prevSelected = newSelected;
      if (zooming && !selectionChanged) return;
      if (rafRef.current !== null) return;
      rafRef.current = requestAnimationFrame(sync);
    });

    return () => {
      unsub();
      map.off("zoomanim");
      map.off("zoomend", onZoomEnd);
      map.off("zoomend");
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      haloRef.current?.remove();
      haloRef.current = null;
      layerRef.current?.remove();
      markersRef.current.clear();
      lastPosTimestampRef.current.clear();
      lastStyleRef.current.clear();
    };
  }, [map, store]);

  return null;
}
