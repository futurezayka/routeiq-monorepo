import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  IconButton,
  Typography,
  Stack,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Select,
  MenuItem,
  InputLabel,
  FormControl,
  Chip,
  InputAdornment,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import PersonAddIcon from "@mui/icons-material/PersonAdd";
import SearchIcon from "@mui/icons-material/Search";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { useListUsersQuery, useCreateUserMutation } from "../api/adminApi";
import { useListVehiclesQuery } from "../api/vehiclesApi";

const PER_PAGE = 15;

const ROLE_COLORS: Record<string, string> = {
  admin: "#F87171",
  dispatcher: "#818CF8",
  driver: "#34D399",
};

const STATUS_COLORS: Record<string, string> = {
  active: "#34D399",
  idle: "#FBBF24",
  offline: "#64748B",
};

const ROLES = [
  { value: "", label: "All Roles" },
  { value: "admin", label: "Admin" },
  { value: "dispatcher", label: "Dispatcher" },
  { value: "driver", label: "Driver" },
];

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("uk-UA", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Admin() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [roleFilter, setRoleFilter] = useState("");
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");

  const { data: usersPage, isFetching } = useListUsersQuery(
    {
      page,
      per_page: PER_PAGE,
      role: roleFilter || undefined,
      search: search || undefined,
    },
    { pollingInterval: 15_000 },
  );

  const users = usersPage?.users ?? [];
  const total = usersPage?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  const { data: vehicles = [] } = useListVehiclesQuery(undefined, {
    pollingInterval: 15_000,
  });
  const [createUser, { isLoading: creating }] = useCreateUserMutation();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    role: "driver",
  });
  const [error, setError] = useState("");

  const vehiclesByDriver = useMemo(() => {
    const m = new Map<string, typeof vehicles>();
    for (const v of vehicles) {
      if (!v.driver_id) continue;
      const list = m.get(v.driver_id) ?? [];
      list.push(v);
      m.set(v.driver_id, list);
    }
    return m;
  }, [vehicles]);

  const handleCreate = async () => {
    setError("");
    if (!form.email || !form.password || !form.full_name) {
      setError("All fields are required");
      return;
    }
    try {
      await createUser(form).unwrap();
      setDialogOpen(false);
      setForm({ email: "", password: "", full_name: "", role: "driver" });
    } catch (e: any) {
      setError(e?.data?.detail ?? "Failed to create user");
    }
  };

  const handleSearch = () => {
    setSearch(searchInput);
    setPage(1);
  };

  const handleRoleChange = (r: string) => {
    setRoleFilter(r);
    setPage(1);
  };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "#0F1117" }}>
      {/* Header */}
      <header
        style={{
          height: 52,
          background: "#0F1117",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          display: "flex",
          alignItems: "center",
          padding: "0 20px",
          gap: 12,
        }}
      >
        <IconButton
          onClick={() => navigate("/")}
          sx={{ color: "#94A3B8", "&:hover": { color: "#F1F5F9" } }}
          size="small"
        >
          <ArrowBackIcon sx={{ fontSize: 18 }} />
        </IconButton>
        <span style={{ fontWeight: 600, fontSize: 15, color: "#F1F5F9", letterSpacing: 0.3 }}>
          Admin Panel
        </span>
        <Chip
          label={`${total} users`}
          size="small"
          sx={{
            bgcolor: "rgba(129,140,248,0.1)",
            color: "#818CF8",
            fontWeight: 600,
            fontSize: 11,
            height: 22,
          }}
        />
        <Chip
          label={`${vehicles.length} vehicles`}
          size="small"
          sx={{
            bgcolor: "rgba(251,191,36,0.1)",
            color: "#FBBF24",
            fontWeight: 600,
            fontSize: 11,
            height: 22,
          }}
        />
        <div style={{ flex: 1 }} />
        <Button
          startIcon={<PersonAddIcon />}
          onClick={() => setDialogOpen(true)}
          variant="contained"
          size="small"
          sx={{
            bgcolor: "#818CF8",
            textTransform: "none",
            fontWeight: 600,
            fontSize: 12,
            borderRadius: "8px",
            "&:hover": { bgcolor: "#6366F1" },
          }}
        >
          New User
        </Button>
      </header>

      <Box sx={{ p: { xs: 1.5, md: 2.5 } }}>
        {/* Toolbar: search + role filter */}
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1.5}
          sx={{ mb: 2 }}
          alignItems={{ sm: "center" }}
        >
          <TextField
            placeholder="Search by name or email..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            onBlur={handleSearch}
            size="small"
            sx={{
              flex: 1,
              maxWidth: { sm: 360 },
              ...fieldSx,
            }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon sx={{ fontSize: 18, color: "#475569" }} />
                </InputAdornment>
              ),
            }}
          />
          <Stack direction="row" spacing={0.5}>
            {ROLES.map((r) => (
              <button
                key={r.value}
                onClick={() => handleRoleChange(r.value)}
                style={{
                  padding: "6px 14px",
                  borderRadius: 6,
                  border: "none",
                  background:
                    roleFilter === r.value
                      ? r.value
                        ? `${ROLE_COLORS[r.value]}25`
                        : "rgba(255,255,255,0.08)"
                      : "transparent",
                  color:
                    roleFilter === r.value
                      ? r.value
                        ? ROLE_COLORS[r.value]
                        : "#E2E8F0"
                      : "#64748B",
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: "pointer",
                  transition: "all 150ms",
                }}
              >
                {r.label}
              </button>
            ))}
          </Stack>
        </Stack>

        {/* Users table card */}
        <Box
          sx={{
            background: "linear-gradient(145deg, #1A1D2A 0%, #161822 100%)",
            border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: "12px",
            overflow: "hidden",
            mb: 2.5,
            opacity: isFetching ? 0.7 : 1,
            transition: "opacity 150ms",
          }}
        >
          <Box sx={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 700 }}>
              <thead>
                <tr>
                  {["Name", "Email", "Role", "Status", "Vehicles", "Created"].map((h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: "left",
                        padding: "12px 14px",
                        color: "#64748B",
                        fontWeight: 600,
                        fontSize: 11,
                        textTransform: "uppercase",
                        letterSpacing: 0.5,
                        borderBottom: "1px solid rgba(255,255,255,0.06)",
                        background: "rgba(0,0,0,0.15)",
                        position: "sticky",
                        top: 0,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const uVehicles = vehiclesByDriver.get(u.id) ?? [];
                  return (
                    <tr
                      key={u.id}
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.02)")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                    >
                      <td style={{ padding: "10px 14px", color: "#E2E8F0", fontWeight: 500 }}>
                        {u.full_name}
                      </td>
                      <td style={{ padding: "10px 14px", color: "#94A3B8", fontFamily: "JetBrains Mono, monospace", fontSize: 12 }}>
                        {u.email}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        <Chip
                          label={u.role}
                          size="small"
                          sx={{
                            bgcolor: `${ROLE_COLORS[u.role] ?? "#64748B"}20`,
                            color: ROLE_COLORS[u.role] ?? "#64748B",
                            fontWeight: 600,
                            fontSize: 11,
                            height: 22,
                          }}
                        />
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: u.is_active ? "#34D399" : "#64748B", fontSize: 12 }}>
                          <span style={{ width: 6, height: 6, borderRadius: "50%", background: u.is_active ? "#34D399" : "#64748B" }} />
                          {u.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        {uVehicles.length === 0 ? (
                          <span style={{ color: "#475569", fontSize: 12 }}>—</span>
                        ) : (
                          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                            {uVehicles.map((v) => (
                              <Chip
                                key={v.id}
                                label={v.license_plate}
                                size="small"
                                sx={{
                                  bgcolor: `${STATUS_COLORS[v.status] ?? "#64748B"}20`,
                                  color: STATUS_COLORS[v.status] ?? "#64748B",
                                  fontWeight: 600,
                                  fontSize: 10,
                                  height: 20,
                                  fontFamily: "JetBrains Mono, monospace",
                                }}
                              />
                            ))}
                          </Stack>
                        )}
                      </td>
                      <td style={{ padding: "10px 14px", color: "#64748B", fontSize: 12, whiteSpace: "nowrap" }}>
                        {formatDate(u.created_at)}
                      </td>
                    </tr>
                  );
                })}
                {users.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ padding: 40, textAlign: "center", color: "#475569" }}>
                      {search ? "No users match your search" : "No users found"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Box>

          {/* Pagination */}
          {totalPages > 1 && (
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                px: 2,
                py: 1.5,
                borderTop: "1px solid rgba(255,255,255,0.06)",
                background: "rgba(0,0,0,0.1)",
              }}
            >
              <Typography sx={{ fontSize: 12, color: "#64748B" }}>
                {(page - 1) * PER_PAGE + 1}–{Math.min(page * PER_PAGE, total)} of {total}
              </Typography>
              <Stack direction="row" spacing={0.5} alignItems="center">
                <IconButton
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  size="small"
                  sx={{ color: "#94A3B8", "&.Mui-disabled": { color: "#334155" } }}
                >
                  <ChevronLeftIcon sx={{ fontSize: 20 }} />
                </IconButton>
                {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                  let p: number;
                  if (totalPages <= 7) {
                    p = i + 1;
                  } else if (page <= 4) {
                    p = i + 1;
                  } else if (page >= totalPages - 3) {
                    p = totalPages - 6 + i;
                  } else {
                    p = page - 3 + i;
                  }
                  return (
                    <button
                      key={p}
                      onClick={() => setPage(p)}
                      style={{
                        width: 28,
                        height: 28,
                        borderRadius: 6,
                        border: "none",
                        background: page === p ? "#818CF8" : "transparent",
                        color: page === p ? "#fff" : "#64748B",
                        fontSize: 12,
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      {p}
                    </button>
                  );
                })}
                <IconButton
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  size="small"
                  sx={{ color: "#94A3B8", "&.Mui-disabled": { color: "#334155" } }}
                >
                  <ChevronRightIcon sx={{ fontSize: 20 }} />
                </IconButton>
              </Stack>
            </Box>
          )}
        </Box>

        {/* Vehicles table */}
        <Box
          sx={{
            background: "linear-gradient(145deg, #1A1D2A 0%, #161822 100%)",
            border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: "12px",
            overflow: "hidden",
          }}
        >
          <Box sx={{ px: 2.5, py: 1.5, borderBottom: "1px solid rgba(255,255,255,0.06)", display: "flex", alignItems: "center", gap: 1 }}>
            <Typography sx={{ fontSize: 13, fontWeight: 600, color: "#CBD5E1", letterSpacing: 0.3 }}>
              Fleet
            </Typography>
            <Chip
              label={`${vehicles.filter((v) => v.status === "active").length} active`}
              size="small"
              sx={{ bgcolor: "rgba(52,211,153,0.1)", color: "#34D399", fontWeight: 600, fontSize: 10, height: 20 }}
            />
          </Box>
          <Box sx={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 600 }}>
              <thead>
                <tr>
                  {["Plate", "Type", "Status", "Driver", "SIM", "Last Seen"].map((h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: "left",
                        padding: "12px 14px",
                        color: "#64748B",
                        fontWeight: 600,
                        fontSize: 11,
                        textTransform: "uppercase",
                        letterSpacing: 0.5,
                        borderBottom: "1px solid rgba(255,255,255,0.06)",
                        background: "rgba(0,0,0,0.15)",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {vehicles.map((v) => {
                  const allUsers = usersPage?.users ?? [];
                  const driver = allUsers.find((u) => u.id === v.driver_id);
                  return (
                    <tr
                      key={v.id}
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.02)")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                    >
                      <td style={{ padding: "10px 14px", color: "#E2E8F0", fontWeight: 600, fontFamily: "JetBrains Mono, monospace" }}>
                        {v.license_plate}
                      </td>
                      <td style={{ padding: "10px 14px", color: "#94A3B8" }}>
                        {v.vehicle_type ?? "—"}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: STATUS_COLORS[v.status] ?? "#64748B", fontSize: 12, fontWeight: 500 }}>
                          <span style={{ width: 6, height: 6, borderRadius: "50%", background: STATUS_COLORS[v.status] ?? "#64748B" }} />
                          {v.status}
                        </span>
                      </td>
                      <td style={{ padding: "10px 14px", color: "#CBD5E1" }}>
                        {driver?.full_name ?? <span style={{ color: "#475569" }}>unassigned</span>}
                      </td>
                      <td style={{ padding: "10px 14px" }}>
                        {v.is_simulated ? (
                          <Chip label="SIM" size="small" sx={{ bgcolor: "rgba(251,191,36,0.12)", color: "#FBBF24", fontWeight: 600, fontSize: 10, height: 20 }} />
                        ) : (
                          <span style={{ color: "#475569", fontSize: 12 }}>—</span>
                        )}
                      </td>
                      <td style={{ padding: "10px 14px", color: "#64748B", fontSize: 12, whiteSpace: "nowrap" }}>
                        {formatDate(v.last_seen)}
                      </td>
                    </tr>
                  );
                })}
                {vehicles.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ padding: 40, textAlign: "center", color: "#475569" }}>
                      No vehicles
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Box>
        </Box>
      </Box>

      {/* Create User Dialog */}
      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        maxWidth="xs"
        fullWidth
        PaperProps={{
          sx: {
            bgcolor: "#1A1D2A",
            backgroundImage: "none",
            border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: "12px",
          },
        }}
      >
        <DialogTitle sx={{ color: "#F1F5F9", fontWeight: 600, fontSize: 16 }}>
          Create User
        </DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: "8px !important" }}>
          <TextField
            label="Full Name"
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            size="small"
            fullWidth
            sx={fieldSx}
          />
          <TextField
            label="Email"
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            size="small"
            fullWidth
            sx={fieldSx}
          />
          <TextField
            label="Password"
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            size="small"
            fullWidth
            sx={fieldSx}
          />
          <FormControl size="small" fullWidth sx={fieldSx}>
            <InputLabel>Role</InputLabel>
            <Select
              value={form.role}
              label="Role"
              onChange={(e) => setForm({ ...form, role: e.target.value })}
            >
              <MenuItem value="driver">Driver</MenuItem>
              <MenuItem value="dispatcher">Dispatcher</MenuItem>
              <MenuItem value="admin">Admin</MenuItem>
            </Select>
          </FormControl>
          {error && (
            <Typography sx={{ color: "#F87171", fontSize: 12 }}>{error}</Typography>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setDialogOpen(false)} sx={{ color: "#94A3B8", textTransform: "none" }}>
            Cancel
          </Button>
          <Button
            onClick={handleCreate}
            disabled={creating}
            variant="contained"
            sx={{
              bgcolor: "#818CF8",
              textTransform: "none",
              fontWeight: 600,
              borderRadius: "8px",
              "&:hover": { bgcolor: "#6366F1" },
            }}
          >
            {creating ? "Creating..." : "Create"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

const fieldSx = {
  "& .MuiOutlinedInput-root": {
    color: "#E2E8F0",
    "& fieldset": { borderColor: "rgba(255,255,255,0.12)" },
    "&:hover fieldset": { borderColor: "rgba(255,255,255,0.25)" },
    "&.Mui-focused fieldset": { borderColor: "#818CF8" },
  },
  "& .MuiInputLabel-root": { color: "#64748B" },
  "& .MuiInputLabel-root.Mui-focused": { color: "#818CF8" },
  "& .MuiSelect-icon": { color: "#64748B" },
};
