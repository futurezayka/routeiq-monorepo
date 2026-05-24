import { useEffect, useRef } from "react";
import { useDispatch, useSelector } from "react-redux";
import type { RootState } from "../store";
import type { PositionUpdate } from "../types";
import {
  batchUpdatePositions,
  setConnected,
  pushEvent,
  highlightRoute,
  addIncidentImpact,
  bumpRecalc,
} from "../slices/liveSlice";
import { baseApi } from "../api/baseApi";

const PING_INTERVAL = 30_000;
const RECONNECT_DELAY = 3_000;
const AGGREGATION_WINDOW_MS = 2_000;

interface PendingIncident {
  incidentId: string;
  type: string;
  severity: string;
  lat: number;
  lng: number;
  affectedRoutes: Set<string>;
  firstSeenAt: number;
  flushTimer: number | null;
}

export function useWebSocket() {
  const token = useSelector((s: RootState) => s.auth.token);
  const dispatch = useDispatch();
  const wsRef = useRef<WebSocket | null>(null);
  const pingRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const bufferRef = useRef<PositionUpdate[]>([]);
  const rafRef = useRef<number | null>(null);
  const flushTimerRef = useRef<number | null>(null);
  const pendingRef = useRef<Map<string, PendingIncident>>(new Map());

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    function flushPositions() {
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      if (bufferRef.current.length > 0) {
        dispatch(batchUpdatePositions(bufferRef.current));
        bufferRef.current = [];
      }
      rafRef.current = null;
    }

    function scheduleFlush() {
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(flushPositions);
      }
      if (flushTimerRef.current === null) {
        flushTimerRef.current = window.setTimeout(flushPositions, 50);
      }
    }

    function flushPending(incidentId: string) {
      const p = pendingRef.current.get(incidentId);
      if (!p) return;
      pendingRef.current.delete(incidentId);

      const count = p.affectedRoutes.size;
      const typeLabel = p.type.charAt(0).toUpperCase() + p.type.slice(1);
      const message = count > 0
        ? `${typeLabel} — ${count} route${count > 1 ? "s" : ""} recalculated`
        : `${typeLabel} reported`;

      const showToast = p.severity === "high";
      dispatch(pushEvent({
        type: "incident",
        severity: p.severity as "low" | "medium" | "high",
        message,
        incidentId: p.incidentId,
        affectedRoutes: count,
        showToast,
      }));

      dispatch(addIncidentImpact({
        incidentId: p.incidentId,
        lat: p.lat,
        lng: p.lng,
      }));

      for (const rid of p.affectedRoutes) {
        dispatch(highlightRoute({ routeId: rid }));
      }

      const routeTags = [...p.affectedRoutes].map((id) => ({
        type: "Route" as const,
        id,
      }));
      dispatch(baseApi.util.invalidateTags(["Incident", ...routeTags]));
    }

    function getOrCreate(incidentId: string): PendingIncident {
      let p = pendingRef.current.get(incidentId);
      if (!p) {
        p = {
          incidentId,
          type: "accident",
          severity: "medium",
          lat: 0,
          lng: 0,
          affectedRoutes: new Set(),
          firstSeenAt: Date.now(),
          flushTimer: null,
        };
        pendingRef.current.set(incidentId, p);
      }
      if (p.flushTimer !== null) window.clearTimeout(p.flushTimer);
      p.flushTimer = window.setTimeout(() => flushPending(incidentId), AGGREGATION_WINDOW_MS);
      return p;
    }

    function connect() {
      if (cancelled) return;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${proto}//${location.host}/api/v1/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        dispatch(setConnected(true));
        pingRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, PING_INTERVAL);
      };

      ws.onmessage = (e) => {
        if (e.data === "pong") return;
        let data: Record<string, unknown>;
        try { data = JSON.parse(e.data as string) as Record<string, unknown>; }
        catch { return; }

        // 1. Position updates
        if (data["vehicle_id"] && data["lat"] != null && data["lng"] != null) {
          bufferRef.current.push({
            vehicle_id: data["vehicle_id"] as string,
            lat: Number(data["lat"]),
            lng: Number(data["lng"]),
            speed: Number(data["speed"] ?? 0),
            heading: data["heading"] != null ? Number(data["heading"]) : undefined,
          });
          scheduleFlush();
          return;
        }

        // 2. Incident notification (ws:incidents)
        if (data["type"] === "new_incident" && data["incident_id"]) {
          const incidentId = data["incident_id"] as string;
          const p = getOrCreate(incidentId);
          p.type = (data["incident_type"] as string) ?? p.type;
          p.severity = (data["severity"] as string) ?? p.severity;
          p.lat = Number(data["lat"] ?? p.lat);
          p.lng = Number(data["lng"] ?? p.lng);
        }

        // 3. Route updates (ws:route-updates)
        if (data["affected_routes"] && Array.isArray(data["affected_routes"])) {
          const routes = data["affected_routes"] as string[];
          const incidentId = (data["incident_id"] as string) ?? `loose-${Date.now()}`;
          const p = getOrCreate(incidentId);
          if (data["severity"]) p.severity = data["severity"] as string;
          if (data["incident_type"]) p.type = data["incident_type"] as string;
          for (const rid of routes) p.affectedRoutes.add(rid);
          for (const rid of routes) dispatch(bumpRecalc(rid));
        }
      };

      ws.onclose = () => {
        dispatch(setConnected(false));
        clearInterval(pingRef.current);
        if (!cancelled) setTimeout(connect, RECONNECT_DELAY);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      cancelled = true;
      clearInterval(pingRef.current);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      if (flushTimerRef.current !== null) window.clearTimeout(flushTimerRef.current);
      flushPositions();
      for (const p of pendingRef.current.values()) {
        if (p.flushTimer !== null) window.clearTimeout(p.flushTimer);
      }
      pendingRef.current.clear();
      wsRef.current?.close();
    };
  }, [token, dispatch]);
}
