import argparse
import asyncio
import logging
import os
import random
import string
import sys

import httpx

from app.agent import VirtualAgent
from app.config import (
    INCIDENT_INJECT_INTERVAL_S,
    N_VEHICLES,
    TELEMETRY_INTERVAL_S,
)
from app.incident_generator import IncidentGenerator
from app.routes import generate_random_endpoints

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("simulator")

SIM_EMAIL = "simulator@routeiq.local"
SIM_PASSWORD = "sim-secret-2026"
MAX_STARTUP_RETRIES = 15
RETRY_DELAY = 2.0


async def wait_for_backend(client: httpx.AsyncClient, url: str) -> None:
    for attempt in range(1, MAX_STARTUP_RETRIES + 1):
        try:
            resp = await client.get(f"{url}/api/v1/vehicles")
            if resp.status_code < 500:
                logger.info("Backend ready (attempt %d)", attempt)
                return
        except httpx.HTTPError:
            pass
        logger.info("Waiting for backend... (%d/%d)", attempt, MAX_STARTUP_RETRIES)
        await asyncio.sleep(RETRY_DELAY)
    logger.error("Backend not reachable after %d attempts", MAX_STARTUP_RETRIES)
    sys.exit(1)


async def ensure_auth(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.post(f"{url}/api/v1/auth/login", json={
        "email": SIM_EMAIL,
        "password": SIM_PASSWORD,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


async def cleanup_old_simulation(
    client: httpx.AsyncClient, url: str, token: str,
) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = await client.post(
            f"{url}/api/v1/admin/reset-simulation", headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            logger.info(
                "Cleaned up old simulation data: %d vehicles, %d incidents, "
                "%d routes, %d telemetry",
                data.get("deleted_vehicles", 0),
                data.get("deleted_incidents", 0),
                data.get("deleted_routes", 0),
                data.get("deleted_telemetry", 0),
            )
        else:
            logger.warning("Cleanup returned %d: %s", resp.status_code, resp.text[:120])
    except httpx.HTTPError as exc:
        logger.warning("Cleanup failed: %s", exc)


async def create_vehicles(
    client: httpx.AsyncClient, url: str, token: str, count: int,
) -> list[str]:
    headers = {"Authorization": f"Bearer {token}"}
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    vehicle_ids: list[str] = []

    for i in range(count):
        plate = f"SIM-{i + 1:03d}-{suffix}"
        resp = await client.post(
            f"{url}/api/v1/vehicles",
            json={"license_plate": plate, "vehicle_type": "van", "is_simulated": True},
            headers=headers,
        )
        if resp.status_code == 201:
            vid = resp.json()["id"]
            vehicle_ids.append(vid)
            logger.info("Vehicle %s → %s", plate, vid[:8])
        else:
            logger.warning("Vehicle %s: %d — %s", plate, resp.status_code, resp.text[:80])

    return vehicle_ids


async def run_simulation(
    backend_url: str,
    osrm_url: str,
    num_agents: int,
    duration: float,
    incident_lambda: float,
    telemetry_interval: float,
) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        await wait_for_backend(client, backend_url)

        token = await ensure_auth(client, backend_url)
        logger.info("Authenticated as %s", SIM_EMAIL)

        await cleanup_old_simulation(client, backend_url, token)

        vehicle_ids = await create_vehicles(client, backend_url, token, num_agents)
        if not vehicle_ids:
            logger.error("No vehicles created — aborting")
            return

        logger.info("Generating %d random routes via OSRM...", num_agents)
        endpoints = await generate_random_endpoints(
            client, osrm_url, num_agents, min_distance_km=2.0,
        )
        if len(endpoints) < num_agents:
            logger.warning(
                "Only %d/%d route endpoints generated, some agents will share routes",
                len(endpoints), num_agents,
            )

        headers = {"Authorization": f"Bearer {token}"}
        agent_routes: dict[str, list[tuple[float, float]]] = {}

        for i, vid in enumerate(vehicle_ids):
            origin, dest = endpoints[i % len(endpoints)]
            resp = await client.post(
                f"{backend_url}/api/v1/routes",
                json={
                    "vehicle_id": vid,
                    "origin_lat": origin[0],
                    "origin_lng": origin[1],
                    "destination_lat": dest[0],
                    "destination_lng": dest[1],
                },
                headers=headers,
            )
            if resp.status_code == 201:
                route_data = resp.json()
                waypoints = route_data.get("waypoints")
                if waypoints and len(waypoints) >= 2:
                    agent_routes[vid] = [(wp[1], wp[0]) for wp in waypoints]
                    logger.info(
                        "Route for %s: %d wpts, %.1f km",
                        vid[:8], len(waypoints),
                        route_data.get("distance_km", 0),
                    )
                else:
                    agent_routes[vid] = [origin, dest]
                    logger.info("Route for %s (fallback — no waypoints)", vid[:8])
            else:
                agent_routes[vid] = [origin, dest]
                logger.warning("Route plan failed for %s: %d", vid[:8], resp.status_code)

        all_waypoints = list(agent_routes.values())

        agents = [
            VirtualAgent(
                vehicle_id=vid,
                route=agent_routes[vid],
                backend_url=backend_url,
                auth_token=token,
                telemetry_interval_min=max(0.5, telemetry_interval * 0.7),
                telemetry_interval_max=telemetry_interval * 1.3,
            )
            for vid in vehicle_ids
        ]

        incident_gen = IncidentGenerator(
            backend_url=backend_url,
            auth_token=token,
            osrm_url=osrm_url,
            incident_lambda=incident_lambda,
            route_waypoints=all_waypoints,
        )

        logger.info(
            "Starting: %d agents, %ds, λ=%.1f inc/min, telemetry ~%.1fs",
            len(agents), int(duration), incident_lambda, telemetry_interval,
        )

        tasks = [asyncio.create_task(a.run(client, duration)) for a in agents]
        tasks.append(asyncio.create_task(incident_gen.run(client, duration)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        telemetry_totals = results[:-1]
        incident_total = results[-1]

        total_telem = sum(c for c in telemetry_totals if isinstance(c, int))
        logger.info("=" * 50)
        logger.info("Simulation complete")
        logger.info("  Agents:     %d", len(agents))
        logger.info("  Duration:   %ds", int(duration))
        logger.info("  Telemetry:  %d points", total_telem)
        logger.info("  Incidents:  %s", incident_total)
        logger.info("=" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(description="RouteIQ Fleet Simulator")
    parser.add_argument(
        "--agents", type=int,
        default=int(os.environ.get("SIM_AGENTS", str(N_VEHICLES))),
    )
    parser.add_argument(
        "--duration", type=int,
        default=int(os.environ.get("SIM_DURATION", "300")),
    )
    parser.add_argument(
        "--backend-url",
        default=os.environ.get("BACKEND_URL", "http://backend:8000"),
    )
    parser.add_argument(
        "--osrm-url",
        default=os.environ.get("OSRM_URL", "http://osrm:5000"),
    )
    parser.add_argument(
        "--incident-lambda", type=float,
        default=float(os.environ.get(
            "SIM_INCIDENT_RATE", str(60.0 / INCIDENT_INJECT_INTERVAL_S),
        )),
        help="Average incidents per minute (Poisson λ)",
    )
    parser.add_argument(
        "--telemetry-interval", type=float,
        default=float(os.environ.get(
            "SIM_TELEMETRY_INTERVAL", str(TELEMETRY_INTERVAL_S),
        )),
        help="Average telemetry send interval in seconds",
    )
    args = parser.parse_args()

    asyncio.run(run_simulation(
        backend_url=args.backend_url,
        osrm_url=args.osrm_url,
        num_agents=args.agents,
        duration=args.duration,
        incident_lambda=args.incident_lambda,
        telemetry_interval=args.telemetry_interval,
    ))


if __name__ == "__main__":
    main()
