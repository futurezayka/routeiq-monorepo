import { useState, useEffect, type FormEvent } from "react";
import { useSelector } from "react-redux";
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
} from "@mui/material";
import MyLocationIcon from "@mui/icons-material/MyLocation";
import { usePlanRouteMutation } from "../../api/routesApi";
import type { RootState } from "../../store";
import type { Vehicle } from "../../types";

const KYIV_CENTER = { lat: 50.4501, lng: 30.5234 };

interface Props {
  open: boolean;
  onClose: () => void;
  vehicles: Vehicle[];
  pickedLocation: { lat: number; lng: number } | null;
  onRequestMapPick: () => void;
  preselectedVehicleId?: string | null;
}

export default function AssignRouteDialog({
  open,
  onClose,
  vehicles,
  pickedLocation,
  onRequestMapPick,
  preselectedVehicleId,
}: Props) {
  const [vehicleId, setVehicleId] = useState("");
  const [destLat, setDestLat] = useState("50.45");
  const [destLng, setDestLng] = useState("30.52");
  const [error, setError] = useState("");
  const [planRoute, { isLoading }] = usePlanRouteMutation();
  const positions = useSelector((s: RootState) => s.live.positions);

  useEffect(() => {
    if (pickedLocation) {
      setDestLat(pickedLocation.lat.toFixed(6));
      setDestLng(pickedLocation.lng.toFixed(6));
    }
  }, [pickedLocation]);

  useEffect(() => {
    if (open) {
      if (preselectedVehicleId && vehicles.some((v) => v.id === preselectedVehicleId)) {
        setVehicleId(preselectedVehicleId);
      } else if (!vehicleId && vehicles.length > 0) {
        setVehicleId(vehicles[0]!.id);
      }
    }
  }, [open, vehicles, vehicleId, preselectedVehicleId]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!vehicleId) {
      setError("Select a vehicle");
      return;
    }
    const pos = positions[vehicleId];
    const origin = pos
      ? { lat: pos.lat, lng: pos.lng }
      : KYIV_CENTER;
    try {
      await planRoute({
        vehicle_id: vehicleId,
        origin_lat: origin.lat,
        origin_lng: origin.lng,
        destination_lat: parseFloat(destLat),
        destination_lng: parseFloat(destLng),
      }).unwrap();
      onClose();
    } catch (err) {
      setError(
        (err as { data?: { detail?: string } })?.data?.detail ??
          "Failed to assign route",
      );
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ pb: 1, fontWeight: 700 }}>Assign Route</DialogTitle>
      <form onSubmit={handleSubmit}>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}

          <TextField
            select
            label="Vehicle"
            value={vehicleId}
            onChange={(e) => setVehicleId(e.target.value)}
            size="small"
            required
          >
            {vehicles.map((v) => (
              <MenuItem key={v.id} value={v.id}>
                {v.license_plate} ({v.status})
              </MenuItem>
            ))}
          </TextField>

          <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="caption" color="text.secondary">
                Destination
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
                value={destLat}
                onChange={(e) => setDestLat(e.target.value)}
                required
                size="small"
                fullWidth
              />
              <TextField
                label="Lng"
                type="number"
                inputProps={{ step: "any" }}
                value={destLng}
                onChange={(e) => setDestLng(e.target.value)}
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
            Assign Route
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
