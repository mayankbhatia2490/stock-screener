# Architecture

StockScreenClaude is a single-tenant market screening platform: React/Vite in the browser, FastAPI for HTTP/API work, Celery for long-running jobs, PostgreSQL for durable state, and Redis for coordination, caching, and Celery transport.

For the visual version, use:

- [System architecture diagram](architecture.html)
- [Data pipeline and storage map](data-pipeline.html)
- [Backend API reference](../backend/README.md)
- [Live app route guide](LIVE_APP_GUIDE.md)

## System Shape

```text
Browser
  |
  v
frontend container (nginx)
  - serves the Vite SPA
  - proxies /api/* to FastAPI
  - serves /static-data/* bundles when static export is enabled
  |
  v
backend container (FastAPI)
  - session auth and feature gates
  - /api/v1/* routers
  - runtime/bootstrap APIs
  - optional MCP HTTP server
  |
  +--> PostgreSQL: durable data
  +--> Redis: broker, results, cache, locks, telemetry gauges
  +--> Celery workers: scans, refreshes, market jobs, theme jobs
  +--> optional Hermes sidecar: assistant gateway
```

Standalone HTTPS deployments add [Caddy](../Caddyfile) in front of nginx. Caddy terminates TLS and reverse-proxies to the frontend container; nginx still serves the SPA and forwards `/api/*` to FastAPI.

## Runtime Boundaries

| Boundary | Owns | Notes |
|---|---|---|
| `frontend/` | React 18, Vite, MUI, TanStack Query/Table, Recharts | Server state lives in React Query; Context is for global UI state such as runtime market, strategy profile, and assistant state. |
| `backend/app/api/v1/` | FastAPI route modules | Thin HTTP layer: auth, feature gates, request/response schemas, dependency resolution. |
| `backend/app/use_cases/` | Application orchestration | Use cases coordinate domain decisions, repositories, task dispatch, and status transitions. |
| `backend/app/domain/` | Market, scanning, feature-store, provider, bootstrap rules | Framework-free business concepts and ports. |
| `backend/app/infra/` | SQLAlchemy repositories, providers, cache/task adapters | Concrete adapters for domain ports. |
| `backend/app/services/` | Legacy/service modules and cross-cutting runtime services | Still contains many business services while newer paths move toward use-case/port boundaries. |
| `backend/app/tasks/` and `backend/app/interfaces/tasks/` | Celery task entry points | Async drivers for the same application logic used by HTTP paths where possible. |

Dependency wiring is centralized in `backend/app/wiring/bootstrap.py`. `RuntimeServices` owns process-scoped providers such as cache bundles, the scan orchestrator, task dispatcher, rate limiter, provider clients, and UI snapshot service.

## Data Ownership

PostgreSQL is the durable source of truth:

- Market universe, prices, fundamentals, provider snapshots
- Feature runs: `feature_runs`, `stock_feature_daily`, `feature_run_pointers`
- Scans: `scans`, `scan_results`
- Breadth, exposure, groups: `market_breadth`, `market_exposure`, `ibd_industry_groups`, `ibd_group_ranks`
- Themes, content, watchlists, validation, telemetry history, assistant conversations

Redis is hot operational state:

- DB 0: Celery broker
- DB 1: Celery result backend
- DB 2: app cache/control plane
- Price/fundamental/benchmark cache payloads
- Data-fetch and market-workload locks
- Rate-limit/circuit-breaker state
- Runtime activity and telemetry gauges

The rule of thumb: **Postgres survives restarts; Redis makes work fast, coordinated, and observable.**

## Data Pipeline

The app has two data clocks:

1. **GitHub release artifacts** seed cold starts and static builds: weekly reference bundles, daily price bundles, IBD classification bundles, and CN shard artifacts.
2. **Runtime Celery pipelines** hydrate and top up local Postgres/Redis from live providers.

The daily market pipeline is the main live path:

```text
queue_daily_market_pipeline(market)
  -> smart_refresh_cache
  -> freshness guards
  -> calculate_daily_breadth_with_gapfill
  -> calculate_market_exposure
  -> calculate_daily_group_rankings_with_gapfill
  -> build_daily_snapshot
  -> publish UI snapshots / static export inputs
```

User scans first try published feature-store paths. If a request cannot be answered from a published feature run, it dispatches `run_bulk_scan` to the market's user-scan queue.

For the detailed producer/store/consumer map, see [data-pipeline.html](data-pipeline.html).

## Queue Topology

Queue names are generated from `backend/app/tasks/market_queues.py`.

| Queue family | Purpose |
|---|---|
| `celery` | General compute, cleanup, finalization, shared work |
| `data_fetch_{market}` plus `data_fetch_shared` | External API and provider refresh work; Docker uses one `celery-datafetch` worker subscribed to enabled market queues with concurrency 1. |
| `market_jobs_{market}` | Per-market scheduled compute: breadth, exposure, group rankings, feature snapshots, IBD sync. |
| `user_scans_{market}` plus `user_scans_shared` | User-triggered scans, isolated from data refresh work. |

Market-scoped locks use matching suffixes, for example `data_fetch_job_lock:hk`. This lets markets run independently while still serializing provider calls inside each data-fetch worker.

## Frontend

The live app is a React Router SPA. Docker builds it with `VITE_API_URL=/api`, then nginx serves the compiled assets and proxies API calls to the backend.

Key frontend conventions:

- API calls use paths under `/v1/...`; the axios base URL supplies `/api`.
- Feature-gated routes such as Themes, Assistant, Tasks, and API docs depend on runtime capabilities.
- Server data belongs in TanStack Query. Avoid duplicating fetched data in global state.
- The canonical route table lives in [LIVE_APP_GUIDE.md](LIVE_APP_GUIDE.md).

## Deployment

| Compose layer | Role |
|---|---|
| `docker-compose.yml` | Base stack: PostgreSQL, Redis, backend, nginx frontend, Celery workers, optional Hermes profile, optional backup profile. |
| `docker-compose.prod.yml` | Production resource/logging overlay. |
| `docker-compose.release.yml` | GHCR image deployment overlay. |
| `docker-compose.https.yml` | Caddy TLS overlay for standalone VPS deployments. |

Enabled markets are configured through `ENABLED_MARKETS` and Compose profiles. The helper `scripts/docker-compose-enabled-markets.sh` expands market profiles and queue subscriptions for the selected deployment.

## Design Rules

- Keep HTTP routes and Celery tasks thin; put business orchestration in use cases/services.
- Prefer domain ports and injected adapters over direct framework calls in business logic.
- Partition market work by market code: queues, locks, cache keys, freshness checks, and bootstrap plans.
- Publish read-optimized state before serving user-facing workflows.
- Treat GitHub release assets as seed/distribution channels, not as a runtime database.
