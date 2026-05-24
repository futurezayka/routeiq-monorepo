import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { PositionUpdate } from "../types";

export interface Notification {
  id: string;
  message: string;
  type: "incident" | "reroute" | "info";
  timestamp: number;
}

export type SystemEventType = "incident" | "reroute" | "anomaly" | "info";

export interface SystemEvent {
  id: string;
  type: SystemEventType;
  severity?: "low" | "medium" | "high";
  message: string;
  incidentId?: string;
  affectedRoutes?: number;
  timestamp: number;
  read: boolean;
}

export interface Toast {
  id: string;
  type: SystemEventType;
  severity?: "low" | "medium" | "high";
  message: string;
  timestamp: number;
}

export interface RouteHighlight {
  routeId: string;
  vehicleId?: string;
  startedAt: number;
}

export interface IncidentImpact {
  incidentId: string;
  lat: number;
  lng: number;
  startedAt: number;
}

interface LiveState {
  positions: Record<string, PositionUpdate>;
  connected: boolean;
  notifications: Notification[];
  events: SystemEvent[];
  unreadCount: number;
  toasts: Toast[];
  routeHighlights: Record<string, RouteHighlight>;
  incidentImpacts: Record<string, IncidentImpact>;
  recalcsByRoute: Record<string, { count: number; updatedAt: number }>;
}

const MAX_EVENTS = 50;
const MAX_TOASTS = 3;

const initialState: LiveState = {
  positions: {},
  connected: false,
  notifications: [],
  events: [],
  unreadCount: 0,
  toasts: [],
  routeHighlights: {},
  incidentImpacts: {},
  recalcsByRoute: {},
};

function nextId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

const liveSlice = createSlice({
  name: "live",
  initialState,
  reducers: {
    updatePosition(state, action: PayloadAction<PositionUpdate>) {
      state.positions[action.payload.vehicle_id] = {
        ...action.payload,
        timestamp: Date.now(),
      };
    },
    batchUpdatePositions(state, action: PayloadAction<PositionUpdate[]>) {
      const now = Date.now();
      for (const pos of action.payload) {
        state.positions[pos.vehicle_id] = { ...pos, timestamp: now };
      }
    },
    setConnected(state, action: PayloadAction<boolean>) {
      state.connected = action.payload;
    },

    // Legacy: kept for compatibility with anywhere that still calls it.
    addNotification(state, action: PayloadAction<Omit<Notification, "id" | "timestamp">>) {
      state.notifications.push({
        ...action.payload,
        id: nextId(),
        timestamp: Date.now(),
      });
      if (state.notifications.length > 20) {
        state.notifications = state.notifications.slice(-20);
      }
    },
    dismissNotification(state, action: PayloadAction<string>) {
      state.notifications = state.notifications.filter((n) => n.id !== action.payload);
    },

    // New system: events history (for bell) + toasts (on-screen).
    pushEvent(
      state,
      action: PayloadAction<{
        type: SystemEventType;
        severity?: "low" | "medium" | "high";
        message: string;
        incidentId?: string;
        affectedRoutes?: number;
        showToast?: boolean;
      }>,
    ) {
      const event: SystemEvent = {
        id: nextId(),
        type: action.payload.type,
        severity: action.payload.severity,
        message: action.payload.message,
        incidentId: action.payload.incidentId,
        affectedRoutes: action.payload.affectedRoutes,
        timestamp: Date.now(),
        read: false,
      };
      state.events.unshift(event);
      if (state.events.length > MAX_EVENTS) state.events.length = MAX_EVENTS;
      state.unreadCount += 1;

      if (action.payload.showToast) {
        state.toasts.push({
          id: event.id,
          type: event.type,
          severity: event.severity,
          message: event.message,
          timestamp: event.timestamp,
        });
        if (state.toasts.length > MAX_TOASTS) {
          state.toasts = state.toasts.slice(-MAX_TOASTS);
        }
      }
    },
    dismissToast(state, action: PayloadAction<string>) {
      state.toasts = state.toasts.filter((t) => t.id !== action.payload);
    },
    markEventsRead(state) {
      state.unreadCount = 0;
      state.events.forEach((e) => { e.read = true; });
    },
    clearEvents(state) {
      state.events = [];
      state.unreadCount = 0;
    },

    // Route reroute highlights
    highlightRoute(
      state,
      action: PayloadAction<{ routeId: string; vehicleId?: string }>,
    ) {
      state.routeHighlights[action.payload.routeId] = {
        routeId: action.payload.routeId,
        vehicleId: action.payload.vehicleId,
        startedAt: Date.now(),
      };
    },
    clearRouteHighlight(state, action: PayloadAction<string>) {
      delete state.routeHighlights[action.payload];
    },

    // Incident impact zone
    addIncidentImpact(
      state,
      action: PayloadAction<{ incidentId: string; lat: number; lng: number }>,
    ) {
      state.incidentImpacts[action.payload.incidentId] = {
        incidentId: action.payload.incidentId,
        lat: action.payload.lat,
        lng: action.payload.lng,
        startedAt: Date.now(),
      };
    },
    clearIncidentImpact(state, action: PayloadAction<string>) {
      delete state.incidentImpacts[action.payload];
    },

    // Recalc counter for vehicle cards
    bumpRecalc(state, action: PayloadAction<string>) {
      const cur = state.recalcsByRoute[action.payload];
      state.recalcsByRoute[action.payload] = {
        count: (cur?.count ?? 0) + 1,
        updatedAt: Date.now(),
      };
    },
  },
});

export const {
  updatePosition,
  batchUpdatePositions,
  setConnected,
  addNotification,
  dismissNotification,
  pushEvent,
  dismissToast,
  markEventsRead,
  clearEvents,
  highlightRoute,
  clearRouteHighlight,
  addIncidentImpact,
  clearIncidentImpact,
  bumpRecalc,
} = liveSlice.actions;

export default liveSlice.reducer;
