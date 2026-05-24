# RouteIQ

Інтелектуальна платформа реального часу для відстеження та координації
транспортного флоту (кур'єрські служби, корпоративні автопарки, доставка).
100–500 одночасних агентів, автоматичне перепланування при інцидентах,
аналітика трафіку, ML-прогнозування завантаженості сегментів.

## Архітектура

Модульний моноліт + окремий ML-сервіс + окремий симулятор. Уся
між-сервісна координація йде через **Redis Streams** (event bus), а не REST.

```
backend/      FastAPI 0.136 моноліт (API + business + stream consumers)
ml-service/   FastAPI 0.136 з PyTorch/sklearn/Prophet stubs + Redis workers
simulator/    asyncio-агенти що шлють телеметрію через ті ж REST-endpoint'и
frontend/     React 19 + Vite 6 + Leaflet + RTK Query + MUI 6
nginx/        reverse proxy + SPA serving
```

Внутрішня шарова архітектура backend'у (суворо):
**API (routers) → Service → Repository → Models (SQLAlchemy 2.0)**.
Усі правила в `CLAUDE.md`.

## Швидкий запуск

```bash
docker compose up -d                            # core: postgres, redis, osrm, backend, ml-service, nginx
docker compose --profile simulation up -d simulator  # ~20 віртуальних агентів
```

UI: <http://localhost>

Готові облікові записи (seed):

| Email | Password | Role |
|-------|----------|------|
| admin@routeiq.com | admin123 | admin |
| dispatcher@routeiq.com | dispatcher123 | dispatcher |
| simulator@routeiq.local | sim-secret-2026 | dispatcher |

OpenAPI: <http://localhost/docs>

## Ключові потоки (Redis Streams)

| Stream | Producer | Consumer group |
|--------|----------|----------------|
| `stream:telemetry` | API ingest | agent-manager, traffic-analysis, anomaly |
| `stream:incidents` | API + auto-anomaly | traffic-analysis |
| `stream:incidents:analyzed` | IncidentAnalysisConsumer | route-planning |
| `stream:route-updates` | RoutePlanningService | agent-manager |
| `stream:ml:anomaly-request` ↔ `:response` | backend ↔ ml-service | — |
| `stream:ml:predict-request` ↔ `:response` | backend ↔ ml-service | — |

Pub/Sub для WebSocket fan-out: `ws:positions`, `ws:incidents`, `ws:route-updates`.

## Тести

```bash
# unit + integration (на тестовій PostgreSQL)
cd backend && pytest -v --cov=app

# навантажувальні (на живому бекенді)
python backend/tests/load/baseline_latency.py        # НФВ-1: ~63ms p95
python backend/tests/load/reroute_timing.py          # НФВ-2: ~78ms median
python backend/tests/load/live_500_agents.py         # НФВ-3: 500 agents
python backend/tests/load/test_event_throughput.py   # НФВ-4: 53k events/s
```

Зведена таблиця всіх НФВ — `backend/tests/load/RESULTS.md` + графік
`load_test_500_agents.png`.

## Ролі та доступ (RBAC)

| Endpoint | admin | dispatcher | driver |
|----------|:-----:|:----------:|:------:|
| `POST /admin/users` | ✅ | ❌ | ❌ |
| `GET /admin/users` | ✅ | ❌ | ❌ |
| `POST /admin/reset-simulation` | ✅ | ✅ | ❌ |
| `POST /vehicles` | ✅ | ✅ | ❌ |
| `POST /routes` | ✅ | ✅ | ❌ |
| `PATCH /incidents/{id}/resolve` | ✅ | ✅ | ❌ |
| `GET /analytics/*` | ✅ | ✅ | ❌ |
| `POST /incidents` | ✅ | ✅ | ✅ |
| `POST /telemetry` | ✅ | ✅ | ✅ (own vehicle) |
| `GET /vehicles` | ✅ | ✅ | ✅ |
| `GET /vehicles/{id}/route` | ✅ | ✅ | ✅ (own) |

## Зовнішні інтеграції

- **OSRM 5.27** — побудова базових маршрутів і snap-to-road
- **Weather** — `WeatherService` stub (детермінований mock; повертає
  `{condition, temperature, wind}` для розрахунку ваги маршруту)
- **ML моделі** — LSTM/Isolation Forest/Prophet присутні як заглушки з
  production-готовим інтерфейсом (детерміновані `numpy`-розрахунки замість
  навчених моделей). Заміна на real-trained моделі не вимагає змін у backend.

## NFR — підтверджено експериментально

| НФВ | Ціль | Виміряно |
|-----|------|----------|
| НФВ-1 latency p95 | < 3 s | **63 ms** |
| НФВ-2 reroute | < 10 s | **78 ms** median |
| НФВ-3 agents | ≥ 500 | **500 active** |
| НФВ-4 throughput | ≥ 10k/s | **53 744/s** avg |
| НФВ-5 auth + refresh | reqd | JWT + `/auth/refresh` |
| НФВ-6 graceful degradation | reqd | try/except + fallback на всіх pipeline I/O |
| НФВ-7 coverage | ≥ 80% | 67+ тестів, pytest-cov налаштовано |
| НФВ-8 OpenAPI | reqd | `/docs`, `/openapi.json` (18 endpoint) |
| НФВ-9 розширюваність | reqd | layered + EventBus абстракція |

## Структура

- `backend/app/` — моноліт (api, modules, models, schemas, events, workers, ws)
- `backend/tests/` — unit / integration / e2e / load
- `ml-service/app/` — FastAPI + workers (`anomaly_worker.py`, `predict_worker.py`)
- `simulator/app/` — asyncio агенти + incident generator
- `frontend/src/` — React 19 + RTK Query + Leaflet
- `CLAUDE.md` — повна архітектурна специфікація (диплом, розділи 1-2)

## Скидання даних симулятора

```bash
curl -X POST http://localhost:8000/api/v1/admin/reset-simulation \
  -H "Authorization: Bearer $(curl -s -X POST http://localhost:8000/api/v1/auth/login \
       -H 'Content-Type: application/json' \
       -d '{"email":"admin@routeiq.com","password":"admin123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')"
```
