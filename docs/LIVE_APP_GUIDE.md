# Live App Guide

This guide covers the server-backed Stock Scanner application: the React UI, FastAPI backend, PostgreSQL database, Redis/Celery workers, and live runtime controls. For deployment, see [Docker Deployment](INSTALL_DOCKER.md). For static GitHub Pages mode, see [Static Site Guide](STATIC_SITE.md).

## First Launch

Server deployments can require browser login before protected API routes are available. Configure `SERVER_AUTH_PASSWORD`, open the app, and sign in with the shared server password.

On a fresh database, the app opens to **First-run market bootstrap**:

- Pick one **primary market** for startup defaults.
- Select additional **enabled markets** only when the host can handle the extra first-run workload.
- Start bootstrap and wait for the primary market to reach `ready`.
- Secondary markets continue hydrating in the background after the workspace opens.

The header status chip links to Operations whenever runtime activity needs inspection.

## Global Controls

- **Runtime activity chip** — shows whether markets are ready, bootstrapping, refreshing, stale, or failed; opens `/operations`.
- **Market selector** — changes the active market context for market-aware pages.
- **Ticker search** — enter a symbol and jump to `/stocks/:ticker`.
- **Strategy profile selector** — switches scan defaults such as screeners, universe, filters, and composite scoring.
- **Scheduled Tasks** — feature-gated task dialog for viewing and triggering registered background jobs.
- **Assistant drawer/page** — feature-gated research assistant when chatbot support is enabled.
- **Theme toggle** — switches dark/light UI mode.
- **Sign out** — appears when server auth is enabled and the browser session is authenticated.

## Live Routes

| Route | Page | What It Does |
|-------|------|--------------|
| `/` | Daily | Daily Snapshot, Key Markets, optional Themes, Watchlists, and Stockbee MM tabs |
| `/scan` | Scan | Multi-market screener with strategy defaults, filter presets, result export, and chart drill-ins |
| `/breadth` | Breadth | StockBee-style breadth indicators, benchmark overlay, movers, and trend windows |
| `/groups` | Groups | IBD-style group/sector rankings, movers, constituents, historical charts, and RRG view |
| `/validation` | Backtest | Deterministic validation of published scan picks and theme alerts over 30/90/180 day windows |
| `/themes` | Themes | Feature-gated theme rankings, grouped/flat views, source management, review queues, alerts, and pipeline runs |
| `/chatbot` | Assistant | Feature-gated AI research assistant with web search, citations, conversation history, and watchlist actions |
| `/stocks/:ticker` | Stock Detail | Charts, fundamentals, technicals, market themes, watchlist actions, and validation history |
| `/operations` | Operations | Runtime activity, telemetry alerts, queue/job inventory, leases, and safe job controls |

Themes, Assistant, and Scheduled Tasks are controlled by backend feature flags and related API keys. If a feature is disabled, its route or control is intentionally absent from the live UI.

## Daily

The Daily page is the starting point for market review. It is split into vertical tabs:

- **Daily Snapshot** — key index/ETF cards, sparklines, scan leaders, market health, and daily context.
- **Key Markets** — market watchlist and TradingView-style context for major benchmarks.
- **Themes** — feature-gated daily theme snapshot when the theme pipeline is enabled.
- **Watchlists** — user watchlists with RS/price sparklines, multi-period change bars, folders, and chart navigation.
- **Stockbee MM** — StockBee-style momentum and market-monitoring view.

## Scan

The Scan page combines multiple screening methodologies:

- Minervini, CANSLIM, IPO, Volume Breakthrough, Setup Engine, and Custom screeners.
- Market/universe selection based on enabled runtime markets.
- Saved filter presets across technical, fundamental, rating, and classification fields.
- Composite scoring, sorting, pagination, and CSV export.
- Chart modal drill-ins, stock detail navigation, and watchlist actions.

If a selected market is still refreshing, scans may be blocked until the relevant runtime activity clears. Use Operations to inspect the queue state.

## Research And Monitoring

- **Breadth** shows advance/decline context, benchmark overlays, up/down movers, and multi-window breadth trends.
- **Groups** ranks industry groups or sectors by relative strength, including movers, constituents, and the Relative Rotation Graph.
- **Stock Detail** is the symbol-level research view with charts, fundamentals, technical indicators, themes, watchlist actions, and validation history.
- **Backtest** summarizes whether published scan picks and theme alerts followed through over selected lookback windows.
- **Themes** is the AI-assisted market narrative surface: rankings, emerging themes, alerts, source controls, candidate review, merge review, article browser, and model/pipeline settings.
- **Assistant** provides conversational research with provider-backed LLMs, optional web search, persistent history, and watchlist-add previews.

## Operations In The UI

Use `/operations` when:

- The header status chip shows a warning, stale state, failed job, or active refresh.
- A scan is blocked by market refresh activity.
- Bootstrap appears slow or stalled.
- You need to inspect queue depth, worker ownership, leases, telemetry alerts, or cancellable jobs.

Detailed runtime and worker guidance lives in [Operations Guide](OPERATIONS.md).
