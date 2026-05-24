import { useState, useEffect, type FormEvent } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  MenuItem,
  Alert,
  Typography,
  Box,
  Stack,
  Chip,
} from "@mui/material";
import MyLocationIcon from "@mui/icons-material/MyLocation";
import { useReportIncidentMutation } from "../../api/incidentsApi";

const TYPES = [
  { value: "accident", label: "Accident" },
  { value: "congestion", label: "Congestion" },
  { value: "roadwork", label: "Road Work" },
  { value: "weather", label: "Weather" },
  { value: "other", label: "Other" },
];

const SEVERITIES = [
  { value: "low", label: "Low", color: "#22c55e" as const },
  { value: "medium", label: "Medium", color: "#f59e0b" as const },
  { value: "high", label: "High", color: "#ef4444" as const },
];

interface Props {
  open: boolean;
  onClose: () => void;
  pickedLocation: { lat: number; lng: number } | null;
  onRequestMapPick: () => void;
}

export default function IncidentForm({
  open,
  onClose,
  pickedLocation,
  onRequestMapPick,
}: Props) {
  const [type, setType] = useState("accident");
  const [severity, setSeverity] = useState("medium");
  const [lat, setLat] = useState("50.45");
  const [lng, setLng] = useState("30.52");
  const [error, setError] = useState("");
  const [report, { isLoading }] = useReportIncidentMutation();

  useEffect(() => {
    if (pickedLocation) {
      setLat(pickedLocation.lat.toFixed(6));
      setLng(pickedLocation.lng.toFixed(6));
    }
  }, [pickedLocation]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await report({
        type,
        severity,
        latitude: parseFloat(lat),
        longitude: parseFloat(lng),
      }).unwrap();
      onClose();
    } catch (err) {
      setError(
        (err as { data?: { detail?: string } })?.data?.detail ??
          "Failed to report",
      );
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ pb: 1, fontWeight: 700 }}>
        Report Incident
      </DialogTitle>
      <form onSubmit={handleSubmit}>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}

          <TextField
            select
            label="Type"
            value={type}
            onChange={(e) => setType(e.target.value)}
            size="small"
          >
            {TYPES.map((t) => (
              <MenuItem key={t.value} value={t.value}>
                {t.label}
              </MenuItem>
            ))}
          </TextField>

          <Box>
            <Typography variant="caption" color="text.secondary" mb={0.5} display="block">
              Severity
            </Typography>
            <Stack direction="row" spacing={1}>
              {SEVERITIES.map((s) => (
                <Chip
                  key={s.value}
                  label={s.label}
                  onClick={() => setSeverity(s.value)}
                  sx={{
                    flex: 1,
                    fontWeight: 600,
                    border: severity === s.value ? `2px solid ${s.color}` : undefined,
                    bgcolor:
                      severity === s.value ? `${s.color}18` : undefined,
                  }}
                  variant={severity === s.value ? "filled" : "outlined"}
                />
              ))}
            </Stack>
          </Box>

          <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="caption" color="text.secondary">
                Location
              </Typography>
              <Button
                size="small"
                startIcon={<MyLocationIcon />}
                onClick={onRequestMapPick}
                sx={{ textTransform: "none", fontSize: 12 }}
              >
                Pick on map
              </Button>
            </Stack>
            <Stack direction="row" spacing={1}>
              <TextField
                label="Lat"
                type="number"
                inputProps={{ step: "any" }}
                value={lat}
                onChange={(e) => setLat(e.target.value)}
                required
                size="small"
                fullWidth
              />
              <TextField
                label="Lng"
                type="number"
                inputProps={{ step: "any" }}
                value={lng}
                onChange={(e) => setLng(e.target.value)}
                required
                size="small"
                fullWidth
              />
            </Stack>
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} sx={{ textTransform: "none" }}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="contained"
            disabled={isLoading}
            sx={{ textTransform: "none", fontWeight: 600 }}
          >
            Report Incident
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
