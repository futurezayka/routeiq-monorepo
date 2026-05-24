import { useSelector } from "react-redux";
import { Box, Typography } from "@mui/material";
import type { RootState } from "../../store";
import type { SystemEvent } from "../../slices/liveSlice";

const SEVERITY_COLOR: Record<string, string> = {
  high: "#EF4444",
  medium: "#F59E0B",
  low: "#22C55E",
};

function emoji(e: SystemEvent): string {
  if (e.type === "incident") {
    if (e.severity === "high") return "🚨";
    return "⚠️";
  }
  if (e.type === "reroute") return "🔀";
  if (e.type === "anomaly") return "📊";
  return "ℹ️";
}

function clock(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function RecentEventsPanel() {
  const events = useSelector((s: RootState) => s.live.events);
  if (events.length === 0) return null;

  return (
    <Box
      sx={{
        position: "absolute",
        bottom: 16,
        left: 16,
        background: "rgba(15,17,23,0.92)",
        borderRadius: 1.5,
        padding: "10px 14px",
        border: "1px solid rgba(255,255,255,0.06)",
        zIndex: 500,
        minWidth: 260,
        maxWidth: 340,
      }}
    >
      <Typography
        sx={{
          fontSize: 10,
          color: "#64748B",
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: 0.5,
          mb: 0.8,
        }}
      >
        Recent events
      </Typography>
      {events.slice(0, 5).map((e) => (
        <Box key={e.id} sx={{ display: "flex", alignItems: "center", gap: 1, mt: 0.4 }}>
          <Typography sx={{ fontSize: 13, lineHeight: 1, fontFamily: "JetBrains Mono, monospace", color: "#64748B" }}>
            {clock(e.timestamp)}
          </Typography>
          <Typography sx={{ fontSize: 13 }}>{emoji(e)}</Typography>
          <Typography
            sx={{
              fontSize: 12,
              color: e.severity ? SEVERITY_COLOR[e.severity] : "#F1F5F9",
              fontWeight: 500,
              flex: 1,
            }}
          >
            {e.message}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}
