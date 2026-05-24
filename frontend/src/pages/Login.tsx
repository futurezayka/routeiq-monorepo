import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";
import {
  Box,
  Card,
  CardContent,
  TextField,
  Button,
  Typography,
  Alert,
} from "@mui/material";
import { useLoginMutation } from "../api/authApi";
import { setCredentials } from "../slices/authSlice";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const navigate = useNavigate();
  const dispatch = useDispatch();

  const [login, { isLoading }] = useLoginMutation();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const res = await login({ email, password }).unwrap();
      dispatch(setCredentials({ token: res.access_token, refreshToken: res.refresh_token }));
      navigate("/", { replace: true });
    } catch (err) {
      const msg =
        (err as { data?: { detail?: string } })?.data?.detail ?? "Invalid credentials";
      setError(msg);
    }
  }

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        bgcolor: "#0F1117",
      }}
    >
      <Card sx={{ width: 380, maxWidth: "95vw", bgcolor: "#1A1D27", border: "1px solid rgba(255,255,255,0.06)" }}>
        <CardContent sx={{ p: 4 }}>
          <Typography align="center" sx={{ mb: 0.5, fontWeight: 700, fontSize: 22, color: "#F1F5F9" }}>
            Route<span style={{ color: "#6366F1" }}>IQ</span>
          </Typography>
          <Typography align="center" sx={{ mb: 3, fontSize: 13, color: "#64748B" }}>
            Fleet Monitoring Dashboard
          </Typography>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          <Box component="form" onSubmit={handleSubmit}>
            <TextField
              label="Email"
              type="email"
              fullWidth
              required
              sx={{ mb: 2 }}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <TextField
              label="Password"
              type="password"
              fullWidth
              required
              sx={{ mb: 2 }}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Button
              type="submit"
              variant="contained"
              fullWidth
              size="large"
              disabled={isLoading}
              sx={{ textTransform: "none", fontWeight: 600, bgcolor: "#6366F1", "&:hover": { bgcolor: "#4F46E5" } }}
            >
              Sign In
            </Button>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
