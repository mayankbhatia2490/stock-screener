# Operations Guide

This guide covers live runtime operations for the server-backed app: first-run bootstrap, enabled-market workers, runtime activity, job controls, telemetry, scheduled tasks, and common recovery paths.

## Runtime Model

The live app stores runtime choices in PostgreSQL and runs market work through Redis/Celery queues.

- `runtime.primary_market` controls the market opened first and used for startup defaults.
- `runtime.enabled_markets` controls which markets the app should hydrate and expose.
- `runtime.bootstrap_state` moves from `not_started` to `running` to `ready`.
- Runtime activity rows report per-market lifecycle, stage, progress, owner task, and warning/failure state.

The UI surfaces this through the header status chip and `/operations`.

## Enabled Market Workers

The default Compose file defines worker services for every supported market, but market-specific workers are behind Compose profiles. Use the helper script to start only the worker profiles required by `ENABLED_MARKETS`:

```bash
ENABLED_MARKETS=US,HK,CN scripts/docker-compose-enabled-markets.sh up -d
```

For `ENABLED_MARKETS=US,HK,CN`, Docker starts US/HK/CN market job and user scan workers. IN/JP/KR/TW/DE/CA/SG/MY/AU worker containers are not created. The global data-fetch worker listens only to `data_fetch_shared,data_fetch_us,data_fetch_hk,data_fetch_cn`.

Keep the first-run wizard's enabled markets within the deployment `ENABLED_MARKETS` set. To add a market later, update `ENABLED_MARKETS` and recreate the stack:

```bash
ENABLED_MARKETS=US,HK,CN,TW scripts/docker-compose-enabled-markets.sh up -d
```

## First-Run Bootstrap

On first launch, choose a primary market and any secondary markets to hydrate in the background. The workspace opens when the primary market is ready; secondary markets continue on their own queues.

Bootstrap stages:

1. **Universe refresh** — seeds the market symbol list. US uses S&P 500 / Russell / NDX via `refresh_stock_universe`; HK / IN / JP / KR / TW / CN / CA / DE / SG / MY / AU use official exchange feeds via `refresh_official_market_universe`.
2. **Benchmark + price refresh** — imports the GitHub daily price bundle first, accepts recent stale bundles during bootstrap, then live-fetches missing/current-session gaps (`7d` top-up for stale symbols, `2y` for no-history symbols).
3. **Fundamentals refresh** — loads quarterly and annual financials.
4. **Breadth calculation** — computes StockBee-style advance/decline data with gap-fill.
5. **Group rankings** — computes IBD-style relative strength group ranks.
6. **Feature snapshot** — US-only daily feature rollup for the Setup Engine.
7. **Initial autoscan** — publishes the first default-profile scan.

Selecting many enabled markets multiplies this work. On smaller hosts, start with one primary market and add markets after the workspace is ready.

## Runtime Activity

The header chip summarizes runtime state:

- **OK** — all markets are idle or ready.
- **Sync / percent** — bootstrap is running.
- **count** — one or more markets have active work.
- **Warn** — a market is stale, stuck, failed, or runtime activity cannot be checked.

Click the chip to open `/operations`.

## Operations Page

The Operations page includes:

- **Market activity** — per-market lifecycle, stage, message, task name, progress, and updated time.
- **Telemetry alerts** — warning/critical alerts with acknowledge controls.
- **Market health summaries** — freshness lag, benchmark age, universe drift, and completeness distribution.
- **Job console** — queued, waiting, reserved, running, stale, stuck, failed, and cancelled jobs across Celery queues.
- **Lease view** — current external-fetch and market-workload ownership.
- **Safe cancellation controls** — revoke, scan cancel, force refresh cancel, or queue removal when the backend marks an action as supported.

Use the filters to narrow by state, queue, market, or task text before cancelling anything.

## Scheduled Tasks

When the tasks feature is enabled, the header settings icon opens **Scheduled Tasks**. The dialog shows:

- registered task display name and description,
- schedule description,
- last run time and duration,
- last status,
- run-now action with polling while a task is active.

Tasks are feature-gated; deployments without task support do not show this control.

## Common Recovery Paths

### Bootstrap Is Slow

- Check `/operations` for active market stages and queue ownership.
- Confirm the host has workers for every market selected in the wizard.
- Reduce enabled markets and restart the stack if the host is resource constrained.
- Check upstream data-provider throttling if many symbols are stuck in price/fundamental refresh.

### Scan Is Blocked

Scans can return a market-refresh blocker while a selected market is hydrating. Wait for the relevant market to leave active refresh state, or inspect `/operations` for stale/stuck work.

### Runtime Activity Looks Stale

Use `/operations` to confirm whether a live worker owns the task. If no worker owns stale running work, restart the affected worker profile and re-run the market refresh or bootstrap step.

### Job Cancellation Fails

Cancellation is intentionally conservative. If a job has no supported cancel strategy, inspect the queue/worker state first, then restart only the affected worker profile if necessary.

### API Docs Are Missing

Interactive API docs are disabled by default in server deployments. Set `SERVER_EXPOSE_API_DOCS=true` only for trusted local development or private environments.

## Related Docs

- [Live App Guide](LIVE_APP_GUIDE.md)
- [Docker Deployment](INSTALL_DOCKER.md)
- [Environment Variables](ENVIRONMENT.md)
- [Architecture](ARCHITECTURE.md)
