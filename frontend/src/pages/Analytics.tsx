import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Box, IconButton, Typography, Stack, Dialog } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import FullscreenIcon from "@mui/icons-material/Fullscreen";
import CloseIcon from "@mui/icons-material/Close";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Legend,
  Area,
  AreaChart,
} from "recharts";
import {
  useGetIncidentStatsQuery,
  useGetFleetEfficiencyQuery,
  useGetHeatmapQuery,
} from "../api/analyticsApi";
import HeatmapView from "../components/Heatmap/HeatmapView";

const SEVERITY_COLORS: Record<string, string> = {
  low: "#60A5FA",
  medium: "#FBBF24",
  high: "#F87171",
};

const TYPE_COLOR_MAP: Record<string, string> = {
  congestion: "#60A5FA",
  accident: "#F87171",
  roadwork: "#FBBF24",
  weather: "#34D399",
  other: "#A78BFA",
};

const TOOLTIP_STYLE = {
  background: "#1E2130",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: 8,
  color: "#E2E8F0",
  fontSize: 12,
  boxShadow: "0 4px 20px rgba(0,0,0,0.4)",
};

const AXIS_STYLE = { fill: "#64748B", fontSize: 11 };

const RANGE_OPTIONS = [
  { value: 1, label: "1h" },
  { value: 6, label: "6h" },
  { value: 24, label: "24h" },
  { value: 72, label: "3d" },
  { value: 168, label: "7d" },
];

function hoursAgo(h: number): string {
  return new Date(Date.now() - h * 3600_000).toISOString();
}

function ChartCard({
  title,
  children,
  span = 6,
}: {
  title: string;
  children: React.ReactNode;
  span?: number;
}) {
  return (
    <Box
      sx={{
        gridColumn: { xs: "span 12", md: `span ${span}` },
        background: "linear-gradient(145deg, #1A1D2A 0%, #161822 100%)",
        border: "1px solid rgba(255,255,255,0.06)",
        borderRadius: "12px",
        p: 2.5,
        transition: "border-color 200ms",
        "&:hover": { borderColor: "rgba(255,255,255,0.12)" },
      }}
    >
      <Typography
        sx={{ fontSize: 13, fontWeight: 600, color: "#CBD5E1", mb: 2, letterSpacing: 0.3 }}
      >
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function StatCard({
  label,
  value,
  color,
  sub,
}: {
  label: string;
  value: string | number;
  color: string;
  sub?: string;
}) {
  return (
    <Box
      sx={{
        flex: "1 1 0",
        minWidth: 130,
        background: "linear-gradient(145deg, #1A1D2A 0%, #161822 100%)",
        border: "1px solid rgba(255,255,255,0.06)",
        borderRadius: "12px",
        p: 2,
        display: "flex",
        flexDirection: "column",
        gap: 0.5,
      }}
    >
      <Typography sx={{ fontSize: 11, color: "#64748B", fontWeight: 500, letterSpacing: 0.5, textTransform: "uppercase" }}>
        {label}
      </Typography>
      <Typography sx={{ fontSize: 24, fontWeight: 700, color, lineHeight: 1.1 }}>
        {value}
      </Typography>
      {sub && (
        <Typography sx={{ fontSize: 11, color: "#475569", mt: 0.25 }}>
          {sub}
        </Typography>
      )}
    </Box>
  );
}

export default function Analytics() {
  const navigate = useNavigate();
  const [hours, setHours] = useState(24);
  const [heatmapFullscreen, setHeatmapFullscreen] = useState(false);

  const range = useMemo(
    () => ({ from: hoursAgo(hours), to: new Date().toISOString() }),
    [hours],
  );

  const { data: stats } = useGetIncidentStatsQuery(range, {
    pollingInterval: 30_000,
  });
  const { data: efficiency } = useGetFleetEfficiencyQuery(range, {
    pollingInterval: 30_000,
  });
  const { data: heatmap } = useGetHeatmapQuery(range, {
    pollingInterval: 60_000,
  });

  const typeData = useMemo(
    () =>
      stats
        ? Object.entries(stats.by_type).map(([name, value]) => ({ name, value }))
        : [],
    [stats],
  );

  const severityData = useMemo(
    () =>
      stats
        ? Object.entries(stats.by_severity).map(([name, value]) => ({
            name,
            value,
          }))
        : [],
    [stats],
  );

  const efficiencyData = useMemo(
    () =>
      efficiency
        ? efficiency.routes.map((r, i) => ({
            index: i + 1,
            planned: r.planned_eta ?? 0,
            actual: Math.round(r.actual_minutes),
            efficiency: r.efficiency ? Math.round(r.efficiency * 100) : 0,
          }))
        : [],
    [efficiency],
  );

  const avgEff = efficiency?.avg_efficiency != null
    ? `${(efficiency.avg_efficiency * 100).toFixed(0)}%`
    : "N/A";

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
          Analytics
        </span>

        <div style={{ flex: 1 }} />

        <div
          style={{
            display: "flex",
            gap: 2,
            background: "rgba(255,255,255,0.04)",
            borderRadius: 6,
            padding: 2,
          }}
        >
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setHours(opt.value)}
              style={{
                padding: "5px 12px",
                borderRadius: 4,
                border: "none",
                background:
                  hours === opt.value ? "#818CF8" : "transparent",
                color:
                  hours === opt.value ? "#fff" : "#64748B",
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 150ms ease",
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </header>

      <Box sx={{ p: 2.5 }}>
        {/* Summary stat cards */}
        <Stack direction="row" spacing={2} sx={{ mb: 2.5, flexWrap: "wrap" }}>
          <StatCard
            label="Total Incidents"
            value={stats?.total ?? 0}
            color="#818CF8"
          />
          <StatCard
            label="Active"
            value={stats?.active_count ?? 0}
            color="#F87171"
            sub="currently unresolved"
          />
          <StatCard
            label="Resolved"
            value={stats?.resolved_count ?? 0}
            color="#34D399"
          />
          <StatCard
            label="Avg Resolution"
            value={stats?.avg_resolution_minutes != null ? `${stats.avg_resolution_minutes.toFixed(1)}m` : "N/A"}
            color="#E2E8F0"
          />
          <StatCard
            label="Routes"
            value={efficiency?.routes_total ?? 0}
            color="#818CF8"
          />
          <StatCard
            label="Avg Efficiency"
            value={avgEff}
            color={
              efficiency?.avg_efficiency != null && efficiency.avg_efficiency >= 0.7
                ? "#34D399"
                : efficiency?.avg_efficiency != null && efficiency.avg_efficiency >= 0.4
                  ? "#FBBF24"
                  : "#F87171"
            }
          />
        </Stack>

        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: "repeat(12, 1fr)",
            gap: 2.5,
          }}
        >
          {/* Heatmap */}
          <Box
            sx={{
              gridColumn: "span 12",
              background: "linear-gradient(145deg, #1A1D2A 0%, #161822 100%)",
              border: "1px solid rgba(255,255,255,0.06)",
              borderRadius: "12px",
              p: 2.5,
              transition: "border-color 200ms",
              "&:hover": { borderColor: "rgba(255,255,255,0.12)" },
            }}
          >
            <Box sx={{ display: "flex", alignItems: "center", mb: 2 }}>
              <Typography
                sx={{ fontSize: 13, fontWeight: 600, color: "#CBD5E1", letterSpacing: 0.3, flex: 1 }}
              >
                Traffic Congestion Heatmap
              </Typography>
              <Typography sx={{ fontSize: 11, color: "#475569", mr: 1.5 }}>
                {heatmap?.points?.length ?? 0} data points
              </Typography>
              <IconButton
                onClick={() => setHeatmapFullscreen(true)}
                size="small"
                sx={{
                  color: "#64748B",
                  "&:hover": { color: "#F1F5F9", bgcolor: "rgba(255,255,255,0.06)" },
                }}
              >
                <FullscreenIcon sx={{ fontSize: 18 }} />
              </IconButton>
            </Box>
            <HeatmapView points={heatmap?.points ?? []} />
          </Box>

          {/* Fullscreen heatmap dialog */}
          <Dialog
            open={heatmapFullscreen}
            onClose={() => setHeatmapFullscreen(false)}
            fullScreen
            PaperProps={{
              sx: {
                bgcolor: "#0F1117",
                backgroundImage: "none",
              },
            }}
          >
            <Box sx={{ position: "relative", height: "100vh" }}>
              <Box
                sx={{
                  position: "absolute",
                  top: 16,
                  left: 16,
                  zIndex: 1000,
                  display: "flex",
                  alignItems: "center",
                  gap: 1.5,
                  bgcolor: "rgba(15,17,23,0.85)",
                  backdropFilter: "blur(8px)",
                  borderRadius: "10px",
                  border: "1px solid rgba(255,255,255,0.08)",
                  px: 2,
                  py: 1,
                }}
              >
                <Typography sx={{ fontSize: 14, fontWeight: 600, color: "#F1F5F9" }}>
                  Traffic Congestion Heatmap
                </Typography>
                <Typography sx={{ fontSize: 11, color: "#64748B" }}>
                  {heatmap?.points?.length ?? 0} points
                </Typography>
                <IconButton
                  onClick={() => setHeatmapFullscreen(false)}
                  size="small"
                  sx={{
                    ml: 1,
                    color: "#94A3B8",
                    "&:hover": { color: "#F1F5F9", bgcolor: "rgba(255,255,255,0.08)" },
                  }}
                >
                  <CloseIcon sx={{ fontSize: 18 }} />
                </IconButton>
              </Box>
              <HeatmapView points={heatmap?.points ?? []} fullscreen />
            </Box>
          </Dialog>

          {/* Incidents by Type */}
          <ChartCard title="Incidents by Type">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={typeData} barCategoryGap="25%">
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="rgba(255,255,255,0.04)"
                  vertical={false}
                />
                <XAxis
                  dataKey="name"
                  tick={AXIS_STYLE}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={AXIS_STYLE}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: "rgba(255,255,255,0.03)" }}
                />
                <Bar dataKey="value" name="Count" radius={[6, 6, 0, 0]}>
                  {typeData.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={TYPE_COLOR_MAP[entry.name] ?? "#A78BFA"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* Incidents by Severity */}
          <ChartCard title="Incidents by Severity">
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={severityData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  innerRadius={55}
                  strokeWidth={0}
                  paddingAngle={3}
                  label={({ name, percent }) =>
                    `${name} ${(percent * 100).toFixed(0)}%`
                  }
                >
                  {severityData.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={SEVERITY_COLORS[entry.name] ?? "#64748B"}
                    />
                  ))}
                </Pie>
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend
                  wrapperStyle={{ fontSize: 11, color: "#94A3B8" }}
                  formatter={(value: string) => (
                    <span style={{ color: "#94A3B8" }}>{value}</span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* Route Efficiency */}
          <ChartCard title="Route Efficiency — Planned vs Actual (minutes)" span={8}>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={efficiencyData} barCategoryGap="20%">
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="rgba(255,255,255,0.04)"
                  vertical={false}
                />
                <XAxis
                  dataKey="index"
                  tick={AXIS_STYLE}
                  axisLine={false}
                  tickLine={false}
                  label={{
                    value: "Route #",
                    position: "insideBottom",
                    offset: -5,
                    ...AXIS_STYLE,
                  }}
                />
                <YAxis tick={AXIS_STYLE} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: "rgba(255,255,255,0.03)" }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11, color: "#94A3B8" }}
                  formatter={(value: string) => (
                    <span style={{ color: "#94A3B8" }}>{value}</span>
                  )}
                />
                <Bar
                  dataKey="planned"
                  name="Planned ETA"
                  fill="#818CF8"
                  radius={[6, 6, 0, 0]}
                />
                <Bar
                  dataKey="actual"
                  name="Actual"
                  fill="#F59E0B"
                  radius={[6, 6, 0, 0]}
                  fillOpacity={0.85}
                />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          {/* Efficiency Ratio */}
          <ChartCard title="Efficiency Ratio (%)" span={4}>
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={efficiencyData}>
                <defs>
                  <linearGradient id="effGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#34D399" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#34D399" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="rgba(255,255,255,0.04)"
                  vertical={false}
                />
                <XAxis
                  dataKey="index"
                  tick={AXIS_STYLE}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={AXIS_STYLE}
                  axisLine={false}
                  tickLine={false}
                  domain={[0, 150]}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => `${v}%`}
                />
                <Area
                  type="monotone"
                  dataKey="efficiency"
                  stroke="#34D399"
                  strokeWidth={2}
                  fill="url(#effGrad)"
                  dot={{ fill: "#34D399", r: 3, strokeWidth: 0 }}
                  activeDot={{ fill: "#34D399", r: 5, strokeWidth: 2, stroke: "#1A1D2A" }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </ChartCard>
        </Box>
      </Box>
    </Box>
  );
}
