import pytest
from httpx import AsyncClient


async def test_predict_returns_valid_structure(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/ml/predict", json={
        "segment_ids": ["seg-1", "seg-2", "seg-3"],
        "features": {"seg-1": 10.0, "seg-2": 20.0, "seg-3": 5.0},
    })
    assert resp.status_code == 200

    body = resp.json()
    assert "predictions" in body
    assert "model_version" in body
    assert len(body["predictions"]) == 3

    for pred in body["predictions"]:
        assert "segment_id" in pred
        assert "congestion" in pred
        assert "avg_speed_kmh" in pred
        assert "confidence" in pred
        assert 0 <= pred["congestion"] <= 1
        assert pred["avg_speed_kmh"] > 0
        assert 0 <= pred["confidence"] <= 1

    ids = [p["segment_id"] for p in body["predictions"]]
    assert ids == ["seg-1", "seg-2", "seg-3"]


async def test_predict_empty_features_uses_defaults(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/ml/predict", json={
        "segment_ids": ["seg-a", "seg-b"],
    })
    assert resp.status_code == 200

    body = resp.json()
    assert len(body["predictions"]) == 2
    for pred in body["predictions"]:
        assert 0 <= pred["congestion"] <= 1


async def test_anomaly_returns_scores(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/ml/anomaly", json={
        "segment_speeds": {
            "seg-1": 45.0,
            "seg-2": 42.0,
            "seg-3": 5.0,
        },
    })
    assert resp.status_code == 200

    body = resp.json()
    assert "anomalies" in body
    assert "model_version" in body
    assert len(body["anomalies"]) == 3

    for anomaly in body["anomalies"]:
        assert "segment_id" in anomaly
        assert "score" in anomaly
        assert "is_anomaly" in anomaly
        assert 0 <= anomaly["score"] <= 1

    slow = next(a for a in body["anomalies"] if a["segment_id"] == "seg-3")
    assert slow["score"] > 0.5
    assert slow["is_anomaly"] is True


async def test_anomaly_similar_speeds_no_anomalies(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/ml/anomaly", json={
        "segment_speeds": {
            "seg-1": 50.0,
            "seg-2": 50.0,
            "seg-3": 50.0,
        },
    })
    assert resp.status_code == 200

    body = resp.json()
    for anomaly in body["anomalies"]:
        assert anomaly["is_anomaly"] is False
        assert anomaly["score"] == pytest.approx(0.0)
