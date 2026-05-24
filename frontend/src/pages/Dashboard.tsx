import { useState, useEffect, useMemo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useSelector, useDispatch } from "react-redux";
import {
  Box,
  Menu,
  MenuItem,
  Typography,
  IconButton,
  Snackbar,
  Alert,
  useMediaQuery,
  SwipeableDrawer,
} from "@mui/material";
import BarChartIcon from "@mui/icons-material/BarChart";
import PersonOutlineIcon from "@mui/icons-material/PersonOutline";
import DirectionsCarIcon from "@mui/icons-material/DirectionsCar";
import DeleteSweepIcon from "@mui/icons-material/DeleteSweep";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import type { RootState } from "../store";
import { useGetMeQuery } from "../api/authApi";
import { useListVehiclesQuery } from "../api/vehiclesApi";
import { useListIncidentsQuery, useResolveIncidentMutation } from "../api/incidentsApi";
import { useListRoutesQuery } from "../api/routesApi";
import { useResetSimulationMutation } from "../api/adminApi";
import { logout, setUser } from "../slices/authSlice";
import { dismissToast, type Toast } from "../slices/liveSlice";
import { useWebSocket } from "../hooks/useWebSocket";
import FleetMap from "../components/Map/FleetMap";
import AgentList from "../components/Sidebar/AgentList";
import IncidentForm from "../components/IncidentForm/IncidentForm";
import AssignRouteDialog from "../components/AssignRouteDialog/AssignRouteDialog";
import NotificationBell from "../components/NotificationBell/NotificationBell";
import RecentEventsPanel from "../components/RecentEventsPanel/RecentEventsPanel";

// Spec §7 — convergent dashboard layout: 320 px expanded sidebar, 56 px
// collapsed rail, 56 px top bar. 320 fits Linear's 14 / 12 / 11 type ramp +
// row + status pill comfortably; 56 fits Samsara-style logo + search + bell.
const SIDEBAR_WIDTH = 320;
const SIDEBAR_COLLAPSED = 56;
const TOPBAR_HEIGHT = 56;

function HeaderStat({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 5 }}>
      <span style={{ fontSize: 12, color: "#64748B", fontWeight: 500 }}>{label}</span>
      <span style={{ fontSize: 14, color: color || "#F1F5F9", fontWeight: 600, fontFamily: "JetBrains Mono, monospace" }}>
        {value}
      </span>
    </span>
  );
}

function HeaderDivider() {
  return <span style={{ width: 1, height: 16, background: "rgba(255,255,255,0.08)", flexShrink: 0 }} />;
}

export default function Dashboard() {
  const [incidentOpen, setIncidentOpen] = useState(false);
  const [assignRouteOpen, setAssignRouteOpen] = useState(false);
  const [assignRouteVehicleId, setAssignRouteVehicleId] = useState<string | null>(null);
  const [pickingFor, setPickingFor] = useState<"incident" | "route" | null>(null);
  const [pickedLocation, setPickedLocation] = useState<{ lat: number; lng: number } | null>(null);
  const [pickingMode, setPickingMode] = useState(false);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const isMobile = useMediaQuery("(max-width:900px)");

  const dispatch = useDispatch();
  const navigate = useNavigate();
  const connected = useSelector((s: RootState) => s.live.connected);
  const toasts = useSelector((s: RootState) => s.live.toasts);

  const { data: user } = useGetMeQuery();
  const { data: vehicles = [] } = useListVehiclesQuery(undefined, { pollingInterval: 15_000 });
  const { data: incidents = [] } = useListIncidentsQuery(undefined, { pollingInterval: 10_000 });
  const { data: routes = [] } = useListRoutesQuery(undefined, { pollingInterval: 15_000 });

  const [resolveIncident] = useResolveIncidentMutation();
  const [resetSimulation, { isLoading: resetting }] = useResetSimulationMutation();

  useWebSocket();

  useEffect(() => {
    if (user) dispatch(setUser(user));
  }, [user, dispatch]);

  useEffect(() => {
    function handlePopupAssign(e: MouseEvent) {
      const btn = (e.target as HTMLElement).closest<HTMLElement>("[data-assign-route]");
      if (btn) {
        const vid = btn.dataset.assignRoute!;
        setAssignRouteVehicleId(vid);
        setAssignRouteOpen(true);
      }
    }
    document.addEventListener("click", handlePopupAssign);
    return () => document.removeEventListener("click", handlePopupAssign);
  }, []);

  const activeVehicles = useMemo(
    () => vehicles.filter((v) => v.status === "active").length,
    [vehicles],
  );
  const activeIncidents = useMemo(
    () => incidents.filter((i) => i.is_active).length,
    [incidents],
  );
  const avgEta = useMemo(() => {
    const withEta = routes.filter((r) => r.eta_minutes != null);
    if (!withEta.length) return 0;
    return Math.round(
      withEta.reduce((s, r) => s + (r.eta_minutes ?? 0), 0) / withEta.length,
    );
  }, [routes]);

  function handleLogout() {
    dispatch(logout());
    navigate("/login", { replace: true });
  }

  const handleViewIncident = useCallback((_lat: number, _lng: number) => {
    // Incidents don't change selectedEntity; clicking "View on map" just
    // pans without selection (handled by IncidentMarker popup).
  }, []);

  const handleResolveIncident = useCallback(
    (id: string) => {
      resolveIncident(id);
    },
    [resolveIncident],
  );

  const handleMapClick = useCallback(
    (lat: number, lng: number) => {
      if (pickingMode) {
        setPickedLocation({ lat, lng });
        setPickingMode(false);
        if (pickingFor === "route") {
          setAssignRouteOpen(true);
        } else {
          setIncidentOpen(true);
        }
      }
    },
    [pickingMode, pickingFor],
  );

  const handleRequestMapPick = useCallback(() => {
    setIncidentOpen(false);
    setPickingFor("incident");
    setPickingMode(true);
  }, []);

  const handleRequestMapPickForRoute = useCallback(() => {
    setAssignRouteOpen(false);
    setPickingFor("route");
    setPickingMode(true);
  }, []);

  const handleReset = useCallback(async () => {
    if (resetting) return;
    await resetSimulation();
  }, [resetSimulation, resetting]);

  const sidePanel = (
    <AgentList
      vehicles={vehicles}
      incidents={incidents}
      routes={routes}
      onViewIncident={handleViewIncident}
      onResolveIncident={handleResolveIncident}
    />
  );

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
        background: "#0F1117",
      }}
    >
      {/* Header — 56 px (Samsara/Linear convergent) */}
      <header
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          height: TOPBAR_HEIGHT,
          background: "var(--bg-surface-1, #121215)",
          borderBottom: "1px solid var(--border-subtle, rgba(255,255,255,0.06))",
          display: "flex",
          alignItems: "center",
          padding: "0 16px",
          zIndex: 1000,
          gap: 16,
          fontFamily: "Inter, sans-serif",
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 15, color: "#F1F5F9", letterSpacing: -0.3, flexShrink: 0 }}>
          Route<span style={{ color: "#6366F1" }}>IQ</span>
        </span>

        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            fontSize: 11,
            fontWeight: 600,
            color: connected ? "#22C55E" : "#EF4444",
            textTransform: "uppercase",
            letterSpacing: 0.5,
            flexShrink: 0,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: connected ? "#22C55E" : "#EF4444",
              display: "inline-block",
            }}
          />
          {connected ? "Live" : "Offline"}
        </span>

        {!isMobile && (
          <>
            <HeaderDivider />
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <HeaderStat label="Fleet" value={vehicles.length} />
              <HeaderStat label="Active" value={activeVehicles} color="#22C55E" />
              <HeaderStat label="Incidents" value={activeIncidents} color={activeIncidents > 0 ? "#EF4444" : "#F1F5F9"} />
              <HeaderStat label="Avg ETA" value={`${avgEta}m`} />
            </div>
          </>
        )}

        <div style={{ flex: 1 }} />

        <div style={{ display: "flex", gap: 2, alignItems: "center" }}>
          <IconButton
            onClick={handleReset}
            disabled={resetting}
            title="Reset simulation data"
            sx={{
              color: resetting ? "#64748B" : "#EF4444",
              "&:hover": { color: "#F87171", bgcolor: "rgba(239,68,68,0.1)" },
            }}
            size="small"
          >
            <DeleteSweepIcon sx={{ fontSize: 18 }} />
          </IconButton>
          <IconButton
            onClick={() => navigate("/analytics")}
            sx={{ color: "#64748B", "&:hover": { color: "#F1F5F9" } }}
            size="small"
            title="Analytics"
          >
            <BarChartIcon sx={{ fontSize: 18 }} />
          </IconButton>
          {user?.role === "admin" && (
            <IconButton
              onClick={() => navigate("/admin")}
              sx={{ color: "#64748B", "&:hover": { color: "#818CF8" } }}
              size="small"
              title="Admin Panel"
            >
              <AdminPanelSettingsIcon sx={{ fontSize: 18 }} />
            </IconButton>
          )}
          <NotificationBell />
          <IconButton
            onClick={(e) => setAnchorEl(e.currentTarget)}
            sx={{ color: "#64748B", "&:hover": { color: "#F1F5F9" } }}
            size="small"
          >
            <PersonOutlineIcon sx={{ fontSize: 18 }} />
          </IconButton>
          <Menu
            anchorEl={anchorEl}
            open={Boolean(anchorEl)}
            onClose={() => setAnchorEl(null)}
            slotProps={{
              paper: {
                sx: {
                  bgcolor: "#1A1D27",
                  border: "1px solid rgba(255,255,255,0.06)",
                  color: "#F1F5F9",
                },
              },
            }}
          >
            {user && (
              <MenuItem disabled>
                <Typography variant="body2" sx={{ color: "#94A3B8" }}>
                  {user.full_name}
                </Typography>
              </MenuItem>
            )}
            <MenuItem
              onClick={() => {
                setAnchorEl(null);
                handleLogout();
              }}
            >
              Logout
            </MenuItem>
          </Menu>
        </div>
      </header>

      {/* Main content — below fixed header */}
      <Box
        sx={{
          display: "flex",
          flex: 1,
          overflow: "hidden",
          marginTop: `${TOPBAR_HEIGHT}px`,
        }}
      >
        {/* Left sidebar — desktop, collapsible. Spec §7: 320 px expanded /
            56 px collapsed (rail). */}
        {!isMobile && (
          <Box
            sx={{
              width: sidebarCollapsed ? SIDEBAR_COLLAPSED : SIDEBAR_WIDTH,
              flexShrink: 0,
              borderRight: "1px solid var(--border-subtle, rgba(255,255,255,0.06))",
              overflow: "hidden",
              bgcolor: "var(--bg-surface-1, #121215)",
              display: "flex",
              flexDirection: "column",
              transition: "width 180ms cubic-bezier(0.4, 0, 0.2, 1)",
            }}
          >
            {/* Collapse toggle — top of rail */}
            <Box sx={{
              height: 40, display: "flex", alignItems: "center",
              justifyContent: sidebarCollapsed ? "center" : "flex-end",
              px: sidebarCollapsed ? 0 : 1,
              borderBottom: "1px solid var(--border-subtle, rgba(255,255,255,0.06))",
            }}>
              <IconButton
                onClick={() => setSidebarCollapsed((v) => !v)}
                size="small"
                sx={{ color: "var(--text-tertiary, #8A8F98)",
                      "&:hover": { color: "var(--text-primary, #F1F5F9)" } }}
                title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              >
                {sidebarCollapsed
                  ? <ChevronRightIcon sx={{ fontSize: 18 }} />
                  : <ChevronLeftIcon sx={{ fontSize: 18 }} />}
              </IconButton>
            </Box>
            {!sidebarCollapsed && (
              <Box sx={{ flex: 1, overflow: "hidden" }}>{sidePanel}</Box>
            )}
          </Box>
        )}

        {/* Map area */}
        <Box
          sx={{
            flex: 1,
            position: "relative",
            cursor: pickingMode ? "crosshair" : undefined,
          }}
        >
          {pickingMode && (
            <Box
              sx={{
                position: "absolute",
                top: 12,
                left: "50%",
                transform: "translateX(-50%)",
                zIndex: 1000,
                bgcolor: "rgba(15,17,23,0.92)",
                color: "#F1F5F9",
                px: 3,
                py: 1,
                borderRadius: 2,
                fontSize: 14,
                fontWeight: 600,
                border: "1px solid rgba(255,255,255,0.06)",
              }}
            >
              Click on the map to set incident location
            </Box>
          )}

          <FleetMap
            vehicles={vehicles}
            incidents={incidents}
            routes={routes}
            onMapClick={handleMapClick}
            onResolveIncident={handleResolveIncident}
          />

          <RecentEventsPanel />

          {/* Assign Route FAB (admin/dispatcher) */}
          {user && (user.role === "admin" || user.role === "dispatcher") && (
            <button
              onClick={() => { setAssignRouteVehicleId(null); setAssignRouteOpen(true); }}
              style={{
                position: "absolute",
                bottom: 120,
                right: isMobile ? 24 : 24,
                padding: "10px 20px",
                background: "#6366F1",
                color: "white",
                border: "none",
                borderRadius: 24,
                fontSize: 14,
                fontWeight: 600,
                cursor: "pointer",
                boxShadow: "0 4px 16px rgba(99,102,241,0.4)",
                zIndex: 500,
              }}
            >
              Assign Route
            </button>
          )}

          {/* Report Incident FAB */}
          <button
            onClick={() => setIncidentOpen(true)}
            style={{
              position: "absolute",
              bottom: 68,
              right: isMobile ? 24 : 24,
              padding: "10px 20px",
              background: "#EF4444",
              color: "white",
              border: "none",
              borderRadius: 24,
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
              boxShadow: "0 4px 16px rgba(239,68,68,0.4)",
              display: "flex",
              alignItems: "center",
              gap: 8,
              zIndex: 500,
              transition: "opacity 150ms ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = "0.9";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = "1";
            }}
          >
            Report Incident
          </button>

          {/* Mobile: button to open side panel */}
          {isMobile && (
            <IconButton
              onClick={() => setMobileDrawerOpen(true)}
              sx={{
                position: "absolute",
                top: 12,
                right: 12,
                zIndex: 1000,
                bgcolor: "rgba(15,17,23,0.92)",
                color: "#F1F5F9",
                border: "1px solid rgba(255,255,255,0.06)",
                "&:hover": { bgcolor: "#242736" },
              }}
            >
              <DirectionsCarIcon />
            </IconButton>
          )}
        </Box>

        {/* Mobile drawer (bottom sheet) */}
        {isMobile && (
          <SwipeableDrawer
            anchor="bottom"
            open={mobileDrawerOpen}
            onClose={() => setMobileDrawerOpen(false)}
            onOpen={() => setMobileDrawerOpen(true)}
            swipeAreaWidth={30}
            disableSwipeToOpen={false}
            PaperProps={{
              sx: {
                height: "70vh",
                borderTopLeftRadius: 16,
                borderTopRightRadius: 16,
                bgcolor: "#0F1117",
                backgroundImage: "none",
              },
            }}
          >
            <Box
              sx={{
                width: 40,
                height: 4,
                bgcolor: "rgba(255,255,255,0.2)",
                borderRadius: 2,
                mx: "auto",
                mt: 1,
                mb: 0.5,
              }}
            />
            {sidePanel}
          </SwipeableDrawer>
        )}
      </Box>

      <IncidentForm
        open={incidentOpen}
        onClose={() => {
          setIncidentOpen(false);
          setPickedLocation(null);
          setPickingFor(null);
        }}
        pickedLocation={pickedLocation}
        onRequestMapPick={handleRequestMapPick}
      />

      <AssignRouteDialog
        open={assignRouteOpen}
        onClose={() => {
          setAssignRouteOpen(false);
          setAssignRouteVehicleId(null);
          setPickedLocation(null);
          setPickingFor(null);
        }}
        vehicles={vehicles}
        pickedLocation={pickedLocation}
        onRequestMapPick={handleRequestMapPickForRoute}
        preselectedVehicleId={assignRouteVehicleId}
      />

      {toasts.slice(-3).map((t: Toast, idx: number) => (
        <Snackbar
          key={t.id}
          open
          autoHideDuration={5000}
          onClose={() => dispatch(dismissToast(t.id))}
          anchorOrigin={{ vertical: "top", horizontal: "right" }}
          sx={{ mt: idx * 7 }}
        >
          <Alert
            onClose={() => dispatch(dismissToast(t.id))}
            severity={t.severity === "high" ? "error" : t.type === "incident" ? "warning" : "info"}
            sx={{
              bgcolor: "#1A1D27",
              color: "#F1F5F9",
              border: "1px solid rgba(255,255,255,0.06)",
              "& .MuiAlert-icon": {
                color: t.severity === "high" ? "#EF4444" : t.type === "incident" ? "#F59E0B" : "#6366F1",
              },
            }}
          >
            {t.message}
          </Alert>
        </Snackbar>
      ))}
    </Box>
  );
}
