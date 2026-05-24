import { useState } from "react";
import { useSelector, useDispatch } from "react-redux";
import {
  Badge,
  IconButton,
  Menu,
  MenuItem,
  Typography,
  Box,
  Divider,
  Button,
} from "@mui/material";
import NotificationsNoneIcon from "@mui/icons-material/NotificationsNone";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import RouteIcon from "@mui/icons-material/Route";
import InsightsIcon from "@mui/icons-material/Insights";
import type { RootState } from "../../store";
import { markEventsRead, clearEvents, type SystemEvent } from "../../slices/liveSlice";

const SEVERITY_COLOR: Record<string, string> = {
  high: "#EF4444",
  medium: "#F59E0B",
  low: "#22C55E",
};

function timeAgo(ts: number): string {
  const sec = Math.floor((Date.now() - ts) / 1000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const h = Math.floor(min / 60);
  return `${h}h ago`;
}

function iconFor(e: SystemEvent) {
  if (e.type === "incident") return <WarningAmberIcon sx={{ fontSize: 18, color: SEVERITY_COLOR[e.severity ?? "medium"] }} />;
  if (e.type === "reroute") return <RouteIcon sx={{ fontSize: 18, color: "#6366F1" }} />;
  if (e.type === "anomaly") return <InsightsIcon sx={{ fontSize: 18, color: "#8B5CF6" }} />;
  return <NotificationsNoneIcon sx={{ fontSize: 18 }} />;
}

export default function NotificationBell() {
  const [anchor, setAnchor] = useState<null | HTMLElement>(null);
  const events = useSelector((s: RootState) => s.live.events);
  const unread = useSelector((s: RootState) => s.live.unreadCount);
  const dispatch = useDispatch();

  function handleOpen(e: React.MouseEvent<HTMLElement>) {
    setAnchor(e.currentTarget);
    if (unread > 0) dispatch(markEventsRead());
  }

  return (
    <>
      <IconButton onClick={handleOpen} sx={{ color: "#64748B", "&:hover": { color: "#F1F5F9" } }} size="small">
        <Badge
          badgeContent={unread}
          color="error"
          max={99}
          sx={{ "& .MuiBadge-badge": { fontSize: 9, height: 14, minWidth: 14 } }}
        >
          <NotificationsNoneIcon sx={{ fontSize: 18 }} />
        </Badge>
      </IconButton>
      <Menu
        anchorEl={anchor}
        open={Boolean(anchor)}
        onClose={() => setAnchor(null)}
        slotProps={{
          paper: {
            sx: {
              bgcolor: "#1A1D27",
              border: "1px solid rgba(255,255,255,0.06)",
              color: "#F1F5F9",
              width: 340,
              maxHeight: 480,
            },
          },
        }}
      >
        <Box sx={{ px: 2, py: 1, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Typography sx={{ fontWeight: 600, fontSize: 13 }}>Notifications</Typography>
          {events.length > 0 && (
            <Button size="small" onClick={() => dispatch(clearEvents())} sx={{ textTransform: "none", fontSize: 11, color: "#64748B" }}>
              Clear all
            </Button>
          )}
        </Box>
        <Divider sx={{ borderColor: "rgba(255,255,255,0.06)" }} />
        {events.length === 0 && (
          <MenuItem disabled sx={{ py: 4, justifyContent: "center" }}>
            <Typography variant="body2" sx={{ color: "#64748B" }}>No notifications yet</Typography>
          </MenuItem>
        )}
        {events.slice(0, 20).map((e) => (
          <MenuItem key={e.id} sx={{ alignItems: "flex-start", py: 1, gap: 1.5, whiteSpace: "normal" }}>
            <Box sx={{ mt: 0.3 }}>{iconFor(e)}</Box>
            <Box sx={{ flex: 1 }}>
              <Typography sx={{ fontSize: 12.5, fontWeight: 500, color: "#F1F5F9" }}>
                {e.message}
              </Typography>
              <Typography sx={{ fontSize: 10.5, color: "#64748B", mt: 0.2 }}>
                {timeAgo(e.timestamp)}
              </Typography>
            </Box>
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}
