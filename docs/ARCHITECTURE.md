# Architecture

Technical overview of StockScreenClaude's system design. For API reference and database schema details, see the [Backend README](../backend/README.md).

## System Overview

```
┌─────────────┐     ┌──────────────────────────────┐     ┌─────────────┐
│   Frontend   │────>│       Backend (FastAPI)       │────>│  PostgreSQL  │
│  React/Vite  │<────│  /api/v1/*                    │<────│              │
│   nginx      │     │                               │     └─────────────┘
└─────────────┘     │  ┌─────────────────────────┐  │     ┌─────────────┐
                     │  │    Celery Workers        │  │────>│    Redis     │
                     │  │  celery | data_fetch     │  │<────│  DB0: broker │
                     │  │  user_scans | beat       │  │     │  DB1: results│
                     │  └─────────────────────────┘  │     │  DB2: cache  │
                     └──────────────────────────────┘     └─────────────┘
```

## Layered Backend Architecture

Clean separation of concerns following Domain-Driven Design:

| Layer | Directory | Responsibility |
|-------|-----------|----------------|
| **Domain** | `domain/` | Business rules, ports (interfaces), value objects |
| **Use Cases** | `use_cases/` | Application services, orchestration |
| **Infrastructure** | `infra/` | SQLAlchemy repositories, Celery tasks, external APIs |
| **API** | `api/` | FastAPI routes, Pydantic schemas, HTTP concerns |

Dependency injection wired in `wiring/bootstrap.py`. Services layer (`services/`) contains 70+ business logic modules.

## Runtime Provider Lifecycle

Process-scoped dependencies are owned by an explicit `RuntimeServices` container and lifecycle-bound by the host runtime (FastAPI app startup, Celery worker process init, or CLI script startup).

| Provider | Scope | Owner | Init | Teardown |
|----------|-------|-------|------|----------|
| `cache_bundle` (`price`, `fundamentals`, `benchmark`) | Process | `RuntimeServices` | Lazy on first provider access | Container dropped at process shutdown |
| `group_rank_service` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `task_registry_service` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `data_fetch_lock` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `groq_key_manager` / `zai_key_manager` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `rate_limiter` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `eps_rating_service` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `yfinance_service` / `finviz_service` / `alphavantage_service` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `data_source_service` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `stock_universe_service` / `ticker_validation_service` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `provider_snapshot_service` / `hybrid_fundamentals_service` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `stock_data_provider` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `scan_orchestrator` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `job_backend` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `task_dispatcher` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| `ui_snapshot_service` | Process | `RuntimeServices` | Lazy | Container dropped at process shutdown |
| MCP HTTP server | Process | FastAPI app state (`app.state.mcp_server`) | Created during FastAPI startup when MCP HTTP is enabled | Removed from app state on shutdown |

## Multi-Screener Orchestrator

The scan orchestrator (`scanners/scan_orchestrator.py`) coordinates all screener types:

- All screeners extend `BaseStockScreener` abstract class
- The `DataPreparationLayer` fetches data once and distributes it to all active screeners
- Composite scoring via configurable aggregation: `weighted_average`, `maximum`, or `minimum`
- Screener registry enables plugin-style scanner registration

### Available Screeners

| Screener | Key Criteria |
|----------|-------------|
| **Minervini Template** | RS > 70-80, Stage 2 uptrend, MA alignment (50>150>200), price 30%+ above 52-week low |
| **CANSLIM** | Quarterly EPS > 25%, Annual EPS growth > 25% (3yr), volume patterns, RS > 70 |
| **IPO Scanner** | Recent IPO status, momentum, volume/price action |
| **Volume Breakthrough** | Unusual volume spikes with confirming price action |
| **Setup Engine** | Base detection, breakout confirmation, Bollinger squeeze, RS line strength |
| **Custom Scanner** | 80+ configurable filters (price, volume, technicals, fundamentals, scores) |

## Celery Task Queues

Market-partitioned queue architecture (bead `StockScreenClaude-asia.9.1`) that separates concerns, prevents rate-limit violations, and enables cross-market parallelism:

| Queue | Workers | Purpose |
|-------|---------|---------|
| `celery` | 4 (local), 2 (Docker) | General compute tasks |
| `data_fetch_{us,hk,jp,tw}` | 1 per market | Per-market external API calls (serialized within a market) |
| `data_fetch_shared` | 1 | Market-agnostic tasks (theme discovery, orphan cleanup) + safety-net default route |
| `user_scans_{us,hk,jp,tw}` | 2 per market | Per-market user-triggered scans |
| `user_scans_shared` | 2 | Market-agnostic scans + safety-net route |

Each market has its own Redis lock key (`data_fetch_job_lock:{market}`), so a US refresh can run in parallel with an HK refresh without either blocking the other. Rate-limit protection inside a market still holds via the per-market worker's concurrency=1. Per-market rate budgets and adaptive backoff land in bead 9.2.

Celery Beat fans out each data-fetch task into one entry per enabled market, routing to the matching queue with `kwargs={"market": "..."}`. Market-scoped task implementations filter the `StockUniverse.market` column to scope their work. See `backend/app/tasks/market_queues.py` for the topology helpers and `backend/app/celery_app.py` for the fan-out.

## Redis Caching Strategy

Three-tier cache: Redis > PostgreSQL > External API.

| DB | Purpose | TTL |
|----|---------|-----|
| DB 0 | Celery broker | N/A |
| DB 1 | Celery results | 24h, auto-cleanup |
| DB 2 | Application cache | Varies |

Application cache (DB 2):
- **Price data:** 7-day TTL, stores 5 years of OHLCV (required for Volume Breakthrough Scanner)
- **Fundamentals:** 7-day TTL with database fallback on Redis miss
- **SPY benchmark:** 24-hour TTL with distributed locking to prevent thundering herd

Shared connection pool managed via `services/redis_pool.py`.

## Feature Store

Pre-computed daily stock snapshots stored in `stock_feature_daily`. A scheduled feature run scores every stock in the universe, then atomically publishes via pointer swap in `feature_run_pointers`.

Lifecycle: `RUNNING` > `COMPLETED` > quality checks > `PUBLISHED` (or `QUARANTINED`)

Scan API endpoints read from the latest published run for fast query responses.

## Database

| Deployment | Database | Notes |
|-----------|----------|-------|
| Local dev / Docker | PostgreSQL | Configured via `DATABASE_URL` / `POSTGRES_*` env vars |

### Key Tables by Category

**Core Stock Data:**
`stock_prices`, `stock_fundamentals`, `stock_universe`, `stock_technicals`

**Feature Store:**
`feature_runs`, `stock_feature_daily`, `feature_run_pointers`

**Scanning:**
`scans`, `scan_results`

**Market Analysis:**
`market_breadth`, `ibd_industry_groups`, `ibd_group_ranks`

**Themes:**
`theme_clusters`, `theme_constituents`, `theme_metrics`, `content_sources`, `content_items`

**User Data:**
`user_watchlists`, `watchlist_items`, `user_themes`, `user_theme_stocks`, `filter_presets`

**Assistant:**
`chatbot_conversations`, `chatbot_messages`

## Application Pages

Canonical live-app route and user-flow documentation lives in the [Live App Guide](LIVE_APP_GUIDE.md).

| Route | Page | Description |
|-------|------|-------------|
| `/` | Daily | Market dashboard with Daily Snapshot, Key Markets, optional Themes, Watchlists, and Stockbee MM tabs |
| `/scan` | Bulk Scanner | Multi-screener scanning with 80+ filters and CSV export |
| `/breadth` | Market Breadth | StockBee-style breadth indicators and trends |
| `/groups` | Group Rankings | IBD industry group rankings with movers |
| `/validation` | Backtest | Deterministic validation for scan picks and theme alerts |
| `/themes` | Themes | Feature-gated AI theme discovery with trending/emerging detection |
| `/chatbot` | Assistant | Feature-gated Hermes-backed assistant with internal market tools and web context |
| `/stocks/:ticker` | Stock Detail | Individual stock analysis with charts and fundamentals |
| `/operations` | Operations | Runtime activity, telemetry alerts, queue/job inventory, and safe job controls |

## API Endpoint Groups

Interactive Swagger docs are disabled by default in server deployments. Set `SERVER_EXPOSE_API_DOCS=true` for trusted local development, then open `http://localhost:8000/docs`.

**Core:**
- `/api/v1/scans` — Scan management and results
- `/api/v1/stocks` — Stock data, fundamentals, chart data
- `/api/v1/features` — Feature store management

**Market Analysis:**
- `/api/v1/breadth` — Market breadth indicators
- `/api/v1/groups` — IBD group rankings
- `/api/v1/themes` — Theme discovery and analysis
- `/api/v1/technical` — Technical indicators
- `/api/v1/validation` — Scan-pick and theme-alert validation

**AI & Research:**
- `/api/v1/assistant` — Assistant sessions, streaming, health, and watchlist preview

**User Data:**
- `/api/v1/user-watchlists` — Watchlist management
- `/api/v1/user-themes` — User theme management
- `/api/v1/market-scan` — Dashboard market scan lists
- `/api/v1/filter-presets` — Saved scan filter configurations
- `/api/v1/strategy-profiles` — Strategy profile metadata and scan defaults

**System:**
- `/api/v1/universe` — Stock universe management
- `/api/v1/cache` — Cache management
- `/api/v1/tasks` — Feature-gated scheduled task status and triggers
- `/api/v1/config` — Admin configuration
- `/api/v1/data-fetch-status` — Data fetch monitoring
- `/api/v1/ticker-validation` — Ticker symbol validation
- `/api/v1/operations` — Queue/job inventory and safe job controls
- `/api/v1/telemetry` — Market telemetry summaries and alerts
- `/api/v1/app-capabilities` and `/api/v1/runtime/*` — App capabilities, bootstrap, runtime markets, and runtime activity

**Health Endpoints (root-level):**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/livez` | GET | Liveness probe (zero dependencies) |
| `/readyz` | GET | Readiness probe (checks DB + Redis) |
| `/health` | GET | Deprecated alias for `/readyz` |
