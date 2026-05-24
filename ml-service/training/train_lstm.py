"""Train LSTM traffic predictor on synthetic dataset."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

torch.manual_seed(42)
np.random.seed(42)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
INPUT_WINDOW = 96
HORIZONS = [4, 12, 24]   # 1h, 3h, 6h (×15min slots)

ROOT = Path(__file__).parent
DATASET = ROOT / "traffic_dataset.csv"
MODELS = ROOT.parent / "saved_models"


class TrafficDS(Dataset):
    def __init__(self, df: pd.DataFrame) -> None:
        X: list[list[list[float]]] = []
        y: list[list[float]] = []
        max_h = max(HORIZONS)
        for _, g in df.sort_values(["segment_id", "timestamp"]).groupby("segment_id"):
            sp = g["speed_kmh"].to_numpy()
            hr = g["hour"].to_numpy()
            dw = g["day_of_week"].to_numpy()
            wt = g["weather_factor"].to_numpy()
            for i in range(len(sp) - INPUT_WINDOW - max_h):
                window = [[
                    float(sp[i + j] / 100),
                    float(np.sin(2 * np.pi * hr[i + j] / 24)),
                    float(np.cos(2 * np.pi * hr[i + j] / 24)),
                    float(np.sin(2 * np.pi * dw[i + j] / 7)),
                    float(np.cos(2 * np.pi * dw[i + j] / 7)),
                    float(wt[i + j]),
                ] for j in range(INPUT_WINDOW)]
                targets = [float(sp[i + INPUT_WINDOW + h - 1] / 100) for h in HORIZONS]
                X.append(window)
                y.append(targets)
        self.X = np.asarray(X, dtype=np.float32)
        self.y = np.asarray(y, dtype=np.float32)

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, i):
        return torch.from_numpy(self.X[i]), torch.from_numpy(self.y[i])


class LSTMNet(nn.Module):
    def __init__(self, input_size: int = 6, hidden_size: int = 64, num_layers: int = 2, output_size: int = 3) -> None:
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=0.2)
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :])


def train(epochs: int = 25, batch_size: int = 128, patience: int = 4) -> dict:
    df = pd.read_csv(DATASET, parse_dates=["timestamp"])
    cutoff = df["timestamp"].quantile(0.8)
    train_df = df[df["timestamp"] < cutoff]
    test_df = df[df["timestamp"] >= cutoff]
    print(f"Train rows: {len(train_df):,}  Test rows: {len(test_df):,}")

    print("Building windows...")
    train_ds = TrafficDS(train_df)
    test_ds = TrafficDS(test_df)
    print(f"Train windows: {len(train_ds):,}  Test windows: {len(test_ds):,}")

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=batch_size)

    model = LSTMNet().to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode="min", factor=0.5, patience=2)
    crit = nn.MSELoss()

    train_losses, test_losses = [], []
    best_test = float("inf")
    best_state = None
    no_improve = 0

    for ep in range(epochs):
        model.train()
        tl = 0.0
        for X, y in train_loader:
            X = X.to(DEVICE); y = y.to(DEVICE)
            pred = model(X)
            loss = crit(pred, y)
            opt.zero_grad()
            loss.backward()
            opt.step()
            tl += loss.item()
        tl /= len(train_loader)

        model.eval()
        vl = 0.0
        with torch.no_grad():
            for X, y in test_loader:
                X = X.to(DEVICE); y = y.to(DEVICE)
                vl += crit(model(X), y).item()
        vl /= len(test_loader)
        scheduler.step(vl)

        train_losses.append(tl); test_losses.append(vl)
        marker = ""
        if vl < best_test - 1e-5:
            best_test = vl
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            no_improve = 0
            marker = "  ★"
        else:
            no_improve += 1
        print(f"Epoch {ep+1:2d}/{epochs}  train={tl:.5f}  test={vl:.5f}{marker}")
        if no_improve >= patience:
            print(f"  early stopping (no improvement for {patience} epochs)")
            break

    # Restore best
    if best_state is not None:
        model.load_state_dict(best_state)

    model.eval()
    preds_list, target_list = [], []
    with torch.no_grad():
        for X, y in test_loader:
            preds_list.append(model(X.to(DEVICE)).cpu().numpy())
            target_list.append(y.numpy())
    preds = np.concatenate(preds_list) * 100      # (N, 3)
    targets = np.concatenate(target_list) * 100   # (N, 3)

    # Per-horizon metrics
    per_horizon: dict[str, dict[str, float]] = {}
    for i, h in enumerate(HORIZONS):
        horizon_min = h * 15
        p = preds[:, i]
        t = targets[:, i]
        mae = float(np.mean(np.abs(p - t)))
        rmse = float(np.sqrt(np.mean((p - t) ** 2)))
        mape = float(np.mean(np.abs((p - t) / (t + 1e-6))) * 100)
        per_horizon[f"{horizon_min}min"] = {
            "mae_kmh": mae, "rmse_kmh": rmse, "mape_pct": mape,
        }
        print(f"  horizon {horizon_min:>3}min: MAE={mae:.2f}km/h  RMSE={rmse:.2f}km/h  MAPE={mape:.2f}%")

    # Aggregate
    mae = float(np.mean(np.abs(preds - targets)))
    rmse = float(np.sqrt(np.mean((preds - targets) ** 2)))
    mape = float(np.mean(np.abs((preds - targets) / (targets + 1e-6))) * 100)
    print(f"\nOverall  MAE={mae:.2f}km/h  RMSE={rmse:.2f}km/h  MAPE={mape:.2f}%")
    print(f"Best test loss: {best_test:.5f} at epoch {test_losses.index(best_test)+1}")

    MODELS.mkdir(exist_ok=True)
    ckpt_path = MODELS / "lstm_v1.pt"
    torch.save({
        "model_state": model.state_dict(),
        "input_window": INPUT_WINDOW,
        "horizons": HORIZONS,
        "input_size": 6,
        "hidden_size": 64,
        "num_layers": 2,
        "output_size": 3,
    }, ckpt_path)
    print(f"Saved model to {ckpt_path}")

    metrics = {
        "mae_kmh": mae,
        "rmse_kmh": rmse,
        "mape_pct": mape,
        "per_horizon": per_horizon,
        "best_epoch": test_losses.index(best_test) + 1,
        "best_test_loss": best_test,
        "epochs_run": len(train_losses),
        "early_stopping_patience": patience,
        "train_losses": train_losses,
        "test_losses": test_losses,
        "test_samples": int(len(targets)),
        "horizons_minutes": [h * 15 for h in HORIZONS],
        "device": str(DEVICE),
    }
    with (MODELS / "lstm_metrics.json").open("w") as f:
        json.dump(metrics, f, indent=2)
    return metrics


if __name__ == "__main__":
    train()
