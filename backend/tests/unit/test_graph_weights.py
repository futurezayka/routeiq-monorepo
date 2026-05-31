import pytest

from app.modules.route_planning.graph_weights import GraphWeightManager


class _FakeRedis:
    """Minimal async dict-backed Redis stand-in for unit tests."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, **_) -> None:
        self._data[key] = value

    def pipeline(self):
        return _FakePipeline(self._data)


class _FakePipeline:
    def __init__(self, data: dict[str, str]) -> None:
        self._data = data
        self._ops: list[str] = []

    def get(self, key: str):
        self._ops.append(key)
        return self

    async def execute(self) -> list[str | None]:
        return [self._data.get(k) for k in self._ops]


@pytest.fixture
def redis():
    return _FakeRedis()


@pytest.fixture
def manager(redis):
    return GraphWeightManager(redis)


async def test_default_weight_is_one(manager):
    w = await manager.get_weight("seg-abc")
    assert w == pytest.approx(1.0)


async def test_incident_factor_applied(manager):
    await manager.update_incident_factor("seg-1", 3.0)
    w = await manager.get_weight("seg-1")
    assert w == pytest.approx(3.0)


async def test_congestion_factor_applied(manager):
    await manager.update_congestion_factor("seg-2", 2.5)
    w = await manager.get_weight("seg-2")
    assert w == pytest.approx(2.5)


async def test_combined_factors_multiply(manager):
    await manager.update_incident_factor("seg-3", 2.0)
    await manager.update_congestion_factor("seg-3", 1.5)
    w = await manager.get_weight("seg-3")
    assert w == pytest.approx(3.0)


async def test_independent_segments(manager):
    await manager.update_incident_factor("seg-a", 5.0)
    w = await manager.get_weight("seg-b")
    assert w == pytest.approx(1.0)


async def test_weight_clamped_to_max(manager):
    await manager.update_incident_factor("seg-x", 15.0)
    await manager.update_congestion_factor("seg-x", 3.0)
    w = await manager.get_weight("seg-x")
    assert w == pytest.approx(10.0)


async def test_non_numeric_redis_value_defaults_to_one(redis, manager):
    redis._data["weight:seg-bad:incident"] = "not_a_number"
    w = await manager.get_weight("seg-bad")
    assert w == pytest.approx(1.0)


async def test_partial_corrupt_value_still_works(redis, manager):
    await manager.update_incident_factor("seg-p", 2.0)
    redis._data["weight:seg-p:congestion"] = "corrupt"
    w = await manager.get_weight("seg-p")
    assert w == pytest.approx(2.0)
