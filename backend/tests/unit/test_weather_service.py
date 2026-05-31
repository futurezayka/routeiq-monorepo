"""Unit tests for weather service — HTTP calls mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.weather.service import (
    WeatherConditions,
    WeatherService,
    _openweather_to_category,
)


# ── _openweather_to_category ────────────────────────────────

def test_tornado():
    assert _openweather_to_category(781, 0, 0) == "tornado"


def test_freezing_rain_511():
    assert _openweather_to_category(511, 0, 0) == "freezing_rain"


def test_thunderstorm_range():
    assert _openweather_to_category(200, 0, 0) == "thunderstorm"
    assert _openweather_to_category(215, 0, 0) == "thunderstorm"
    assert _openweather_to_category(232, 0, 0) == "thunderstorm"


def test_drizzle_range():
    assert _openweather_to_category(300, 0, 0) == "light_rain"
    assert _openweather_to_category(321, 0, 0) == "light_rain"


def test_heavy_rain_by_mm():
    assert _openweather_to_category(500, 8.0, 0) == "heavy_rain"


def test_heavy_rain_by_code():
    for code in (502, 503, 504, 522):
        assert _openweather_to_category(code, 1.0, 0) == "heavy_rain"


def test_moderate_rain_by_mm():
    assert _openweather_to_category(500, 3.0, 0) == "moderate_rain"


def test_moderate_rain_by_code():
    for code in (501, 521, 531):
        assert _openweather_to_category(code, 0, 0) == "moderate_rain"


def test_light_rain_500():
    assert _openweather_to_category(500, 1.0, 0) == "light_rain"


def test_snow_freezing_range():
    for code in (611, 612, 613):
        assert _openweather_to_category(code, 0, 0) == "freezing_rain"


def test_heavy_snow_by_mm():
    assert _openweather_to_category(600, 0, 3.0) == "heavy_snow"


def test_heavy_snow_by_code():
    for code in (601, 602, 621, 622):
        assert _openweather_to_category(code, 0, 0) == "heavy_snow"


def test_light_snow():
    assert _openweather_to_category(600, 0, 0.5) == "light_snow"


def test_fog_low_vis():
    for code in (701, 711, 721, 731, 741, 751, 761, 762, 771):
        assert _openweather_to_category(code, 0, 0) == "fog_low_vis"


def test_clear_800():
    assert _openweather_to_category(800, 0, 0) == "clear"


def test_clear_unknown_code():
    assert _openweather_to_category(900, 0, 0) == "clear"


# ── WeatherConditions ────────────────────────────────────────

def test_weight_factor_clear():
    wc = WeatherConditions(temperature_c=20, condition="clear", wind_kmh=10)
    assert wc.weight_factor == 1.0


def test_weight_factor_heavy_rain():
    wc = WeatherConditions(temperature_c=15, condition="heavy_rain", wind_kmh=30)
    assert wc.weight_factor == 1.25


def test_weight_factor_tornado():
    wc = WeatherConditions(temperature_c=25, condition="tornado", wind_kmh=100)
    assert wc.weight_factor == 5.0


def test_weight_factor_unknown_uses_fallback():
    wc = WeatherConditions(temperature_c=10, condition="alien_weather", wind_kmh=5)
    assert wc.weight_factor == 1.0


def test_source_default():
    wc = WeatherConditions(temperature_c=10, condition="clear", wind_kmh=5)
    assert wc.source == "stub"


# ── WeatherService.get_current ────────────────────────────────

async def test_get_current_stub_when_no_api_key():
    with patch("app.modules.weather.service.settings") as mock_s:
        mock_s.OPENWEATHER_API_KEY = ""
        result = await WeatherService().get_current(50.4, 30.5)
    assert isinstance(result, WeatherConditions)
    assert result.source == "stub"


async def test_get_current_falls_back_on_api_error():
    with patch("app.modules.weather.service.settings") as mock_s:
        mock_s.OPENWEATHER_API_KEY = "test-key"
        svc = WeatherService()
        with patch.object(svc, "_fetch_openweather", side_effect=Exception("API down")):
            result = await svc.get_current(50.4, 30.5)
    assert result.source == "stub"


async def test_get_current_uses_openweather_when_key_present():
    expected = WeatherConditions(
        temperature_c=18.0, condition="light_rain", wind_kmh=12.0, source="openweather",
    )
    with patch("app.modules.weather.service.settings") as mock_s:
        mock_s.OPENWEATHER_API_KEY = "test-key"
        svc = WeatherService()
        with patch.object(svc, "_fetch_openweather", return_value=expected):
            result = await svc.get_current(50.4, 30.5)
    assert result.source == "openweather"
    assert result.condition == "light_rain"


# ── WeatherService._fetch_openweather ────────────────────────

def _weather_data(cond_id=800, main="Clear", temp=20.0, wind=3.0, rain=0, snow=0):
    data = {
        "weather": [{"id": cond_id, "main": main}],
        "main": {"temp": temp},
        "wind": {"speed": wind},
    }
    if rain:
        data["rain"] = {"1h": rain}
    if snow:
        data["snow"] = {"1h": snow}
    return data


def _mock_http(json_data):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


async def test_fetch_openweather_clear():
    mock_client = _mock_http(_weather_data())
    with patch("app.modules.weather.service.httpx.AsyncClient", return_value=mock_client):
        result = await WeatherService()._fetch_openweather(50.4, 30.5)
    assert result.condition == "clear"
    assert result.temperature_c == 20.0
    assert result.wind_kmh == pytest.approx(10.8)
    assert result.source == "openweather"


async def test_fetch_openweather_rain():
    mock_client = _mock_http(_weather_data(cond_id=500, main="Rain", temp=15.5, wind=5.0, rain=1.0))
    with patch("app.modules.weather.service.httpx.AsyncClient", return_value=mock_client):
        result = await WeatherService()._fetch_openweather(50.4, 30.5)
    assert result.condition == "light_rain"
    assert result.temperature_c == 15.5


async def test_fetch_openweather_snow():
    mock_client = _mock_http(_weather_data(cond_id=601, main="Snow", temp=-2.0, wind=3.0, snow=3.0))
    with patch("app.modules.weather.service.httpx.AsyncClient", return_value=mock_client):
        result = await WeatherService()._fetch_openweather(50.4, 30.5)
    assert result.condition == "heavy_snow"
    assert result.temperature_c == -2.0


async def test_fetch_openweather_no_wind():
    mock_client = _mock_http({"weather": [{"id": 800, "main": "Clear"}], "main": {"temp": 25.0}})
    with patch("app.modules.weather.service.httpx.AsyncClient", return_value=mock_client):
        result = await WeatherService()._fetch_openweather(50.4, 30.5)
    assert result.wind_kmh == 0.0
