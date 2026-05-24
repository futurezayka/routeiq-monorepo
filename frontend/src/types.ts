export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  full_name: string;
  role?: string;
}

export interface Vehicle {
  id: string;
  driver_id: string;
  license_plate: string;
  vehicle_type: string | null;
  status: string;
  is_simulated: boolean;
  last_seen: string | null;
}

export interface Incident {
  id: string;
  reported_by: string | null;
  type: string;
  severity: string;
  latitude: number;
  longitude: number;
  is_active: boolean;
  is_simulated: boolean;
  reported_at: string;
  resolved_at: string | null;
}

export interface IncidentCreate {
  type: string;
  severity: string;
  latitude: number;
  longitude: number;
}

export interface RouteCreate {
  vehicle_id: string;
  origin_lat: number;
  origin_lng: number;
  destination_lat: number;
  destination_lng: number;
}

export interface Route {
  id: string;
  vehicle_id: string;
  status: string;
  origin_lat: number;
  origin_lng: number;
  destination_lat: number;
  destination_lng: number;
  waypoints: number[][] | null;
  distance_km: number | null;
  eta_minutes: number | null;
  recalculation_count: number;
  created_at: string;
}

export interface PositionUpdate {
  vehicle_id: string;
  lat: number;
  lng: number;
  speed: number;
  heading?: number;
  timestamp?: number;
}

export interface HeatmapPoint {
  lat: number;
  lng: number;
  congestion_level: number;
}

export interface HeatmapResponse {
  points: HeatmapPoint[];
  time_from: string;
  time_to: string;
}

export interface IncidentStatsResponse {
  total: number;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
  avg_resolution_minutes: number | null;
  active_count: number;
  resolved_count: number;
  time_from: string;
  time_to: string;
}

export interface RouteEfficiencyRow {
  route_id: string;
  planned_eta: number | null;
  actual_minutes: number;
  efficiency: number | null;
}

export interface FleetEfficiencyResponse {
  routes_total: number;
  avg_efficiency: number | null;
  avg_recalculations: number;
  routes: RouteEfficiencyRow[];
  time_from: string;
  time_to: string;
}
