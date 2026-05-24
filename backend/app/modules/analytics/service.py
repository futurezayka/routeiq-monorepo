from datetime import datetime

from app.modules.analytics.repository import AnalyticsRepository
from app.schemas.analytics import (
    FleetEfficiencyResponse,
    HeatmapPoint,
    HeatmapResponse,
    IncidentStatsResponse,
    RouteEfficiencyRow,
)

FREE_FLOW_SPEED_KMH = 60.0


class AnalyticsService:
    def __init__(self, repo: AnalyticsRepository) -> None:
        self._repo = repo

    async def get_traffic_heatmap(
        self, time_from: datetime, time_to: datetime,
    ) -> HeatmapResponse:
        grid = await self._repo.get_speed_grid(time_from, time_to)
        points = [
            HeatmapPoint(
                lat=cell["lat"],
                lng=cell["lng"],
                congestion_level=round(
                    max(0.0, min(1.0, 1.0 - cell["avg_speed"] / FREE_FLOW_SPEED_KMH)),
                    3,
                ),
            )
            for cell in grid
        ]
        return HeatmapResponse(points=points, time_from=time_from, time_to=time_to)

    async def get_incident_stats(
        self, time_from: datetime, time_to: datetime,
    ) -> IncidentStatsResponse:
        incidents = await self._repo.get_incident_history(time_from, time_to)

        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        active_count = 0
        resolved_count = 0
        resolution_minutes: list[float] = []

        for inc in incidents:
            by_type[inc.type] = by_type.get(inc.type, 0) + 1
            by_severity[inc.severity] = by_severity.get(inc.severity, 0) + 1
            if inc.is_active:
                active_count += 1
            else:
                resolved_count += 1
            if inc.resolved_at and inc.reported_at:
                delta = (inc.resolved_at - inc.reported_at).total_seconds() / 60.0
                resolution_minutes.append(delta)

        avg_res = (
            sum(resolution_minutes) / len(resolution_minutes)
            if resolution_minutes
            else None
        )

        return IncidentStatsResponse(
            total=len(incidents),
            by_type=by_type,
            by_severity=by_severity,
            avg_resolution_minutes=round(avg_res, 1) if avg_res is not None else None,
            active_count=active_count,
            resolved_count=resolved_count,
            time_from=time_from,
            time_to=time_to,
        )

    async def get_fleet_efficiency(
        self, time_from: datetime, time_to: datetime,
    ) -> FleetEfficiencyResponse:
        rows = await self._repo.get_route_efficiency(time_from, time_to)

        route_items: list[RouteEfficiencyRow] = []
        efficiencies: list[float] = []
        recalc_total = 0

        for row in rows:
            eff = None
            actual = row["actual_minutes"]
            if row["planned_eta"] and actual and actual > 0:
                eff = row["planned_eta"] / actual
                efficiencies.append(eff)
            recalc_total += row.get("recalculation_count", 0)
            route_items.append(RouteEfficiencyRow(
                route_id=row["route_id"],
                planned_eta=row["planned_eta"],
                actual_minutes=actual or 0.0,
                efficiency=round(eff, 3) if eff is not None else None,
            ))

        avg_eff = sum(efficiencies) / len(efficiencies) if efficiencies else None
        avg_recalc = recalc_total / len(rows) if rows else 0.0

        return FleetEfficiencyResponse(
            routes_total=len(rows),
            avg_efficiency=round(avg_eff, 3) if avg_eff is not None else None,
            avg_recalculations=round(avg_recalc, 2),
            routes=route_items,
            time_from=time_from,
            time_to=time_to,
        )
