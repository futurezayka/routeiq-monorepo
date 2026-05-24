import type { RootState } from "../store";
import { routesApi } from "../api/routesApi";
import { vehiclesApi } from "../api/vehiclesApi";
import type { Route, Vehicle } from "../types";

/**
 * Read the cached "list routes" RTK Query result without subscribing.
 * Returns [] before the first fetch completes.
 */
export function getCachedRoutes(state: RootState): Route[] {
  const entry = routesApi.endpoints.listRoutes.select()(state);
  return entry.data ?? [];
}

export function getCachedVehicles(state: RootState): Vehicle[] {
  const entry = vehiclesApi.endpoints.listVehicles.select()(state);
  return entry.data ?? [];
}

export function selectActiveRouteForVehicle(
  state: RootState,
  vehicleId: string,
): Route | undefined {
  return getCachedRoutes(state).find(
    (r) => r.vehicle_id === vehicleId && r.status === "active",
  );
}

export function selectRouteById(
  state: RootState,
  routeId: string,
): Route | undefined {
  return getCachedRoutes(state).find((r) => r.id === routeId);
}

export function selectVehicleById(
  state: RootState,
  vehicleId: string,
): Vehicle | undefined {
  return getCachedVehicles(state).find((v) => v.id === vehicleId);
}

/**
 * The route that should be drawn in SELECTED style.
 * - selectedEntity={vehicle, id} → active route of that vehicle
 * - selectedEntity={route, id}   → that route directly
 * - null                          → null
 */
export function selectHighlightedRouteId(state: RootState): string | null {
  const sel = state.ui.selectedEntity;
  if (!sel) return null;
  if (sel.type === "route") return sel.id;
  const r = selectActiveRouteForVehicle(state, sel.id);
  return r?.id ?? null;
}

/**
 * The vehicle that should be drawn in SELECTED style.
 * - selectedEntity={vehicle, id} → that vehicle
 * - selectedEntity={route, id}   → vehicle that drives this route
 */
export function selectHighlightedVehicleId(state: RootState): string | null {
  const sel = state.ui.selectedEntity;
  if (!sel) return null;
  if (sel.type === "vehicle") return sel.id;
  const r = selectRouteById(state, sel.id);
  return r?.vehicle_id ?? null;
}
