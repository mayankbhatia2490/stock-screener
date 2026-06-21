# Minervini X List Feature Research

Date: 2026-06-20

Source: X list `Minervini` / `1522014550211457024`, read through the local `xui-reader` skill.

Target repo: `https://github.com/xang1234/stock-screener` (local checkout remote matches this URL).

## Executive Take

The most compelling feature is a **Social Signal Queue**: a ranked view that turns X-list chatter into scan-confirmed stock candidates. The repo is unusually compatible with this because it already has X/Twitter ingestion, theme extraction, theme metrics, scan rows with `market_themes`, Setup Engine fields, Market Health & Exposure, watchlists, and stock detail pages.

Recommended first slice:

1. Add the Minervini list as a Twitter/X `ContentSource`.
2. Extract cashtags/themes into existing `ContentItem`, `ThemeMention`, `ThemeConstituent`, and `ThemeMetrics` paths.
3. Add a queue card/table that ranks tickers by social mention velocity plus existing technical confirmation: RS, 52-week high proximity, dollar volume, Setup Engine readiness, group rank, and market exposure.
4. Add one-click "scan these names" and "add to watchlist" actions.

Mockup artifact: [Social Signal Queue mockup](minervini_social_signal_queue_mockup.svg)

## Pull Summary

Window analyzed: 2026-05-20 through 2026-06-20.

Raw list pull:

- 937 unique tweet IDs with text/date after dedupe from the xui payload.
- 882 timestamped, text-bearing posts in the requested one-month window.
- 384 posts classified as investment/stocks/trading related and used for analysis.
- 191 unique cashtags and 585 cashtag mentions in investment-related posts.
- Top recurring cashtags: `$MU`, `$SNDK`, `$SPCX`, `$BE`, `$INTC`, `$ARM`, `$NBIS`, `$MRVL`, `$SPY`, `$WDC`, `$HOOD`, `$ALAB`, `$DELL`, `$QQQ`, `$SNOW`.

Caveats:

- The xui payload frequently omitted author handles, so this report uses tweet URLs rather than author attribution.
- Some records are retweets or quote/context fragments; classification intentionally favored stock/trading posts and excluded lifestyle, politics, jokes, music, and generic replies.
- Engagement fields were used only as rough ranking signals where present.

## Signal Clusters

| Cluster | Count | What appeared | Product implication |
| --- | ---: | --- | --- |
| Portfolio / watchlist / baskets | 72 | Top holdings, position adds/trims, basket performance, "hold runners" commentary | Users want candidate lists that become watchlists and monitored baskets. |
| Leader / new-high scan workflow | 71 | High dollar volume leaders, 52-week highs, relative strength, 8/10-week moving average discipline, breakout setups | Strong fit for prebuilt scan presets and a "leader queue" UI. |
| Options / dark-pool flow | 40 | MU/SNDK/NVDA/QCOM call flow, dark pool prints, gamma comments | Useful as optional catalyst badges, but real data requires a provider. |
| Social-confirmed themes / sector rotation | 25 | AI infrastructure, semis, memory, neoclouds, solar-for-AI, industry concentration, ETF inflows | Strong fit for existing theme discovery and group/RRG surfaces. |
| Market health / exposure | 25 | Healthy uptrend gating, hold-runners-vs-new-buys, drawdown behavior, market direction first | Already aligns with `MarketHealthExposure` and the exposure dashboard branch. |
| Fundamental catalyst / company thesis | 21 | Chip resistor price hikes, Intel/Apple manufacturing, HIMS/ENHA peptide thesis, MSTR balance-sheet criticism | Good for "why mentioned" excerpts attached to stock detail/theme detail. |
| Journal / process / execution | 19 | Darvas review, setup study, stops, alerts, execution discipline | Medium-fit user workflow feature: trade journal from scan snapshots. |

## Representative Source Links

Social themes and rotation:

- AI infrastructure tickers across chips, foundry, memory, networking, and photonics: https://x.com/i/web/status/2067641327194349574
- Semiconductor ETF inflow / possible euphoria signal: https://x.com/i/web/status/2068051350798135324
- Daily workflow of sorting top movers by industry/theme: https://x.com/i/web/status/2067753582670307643
- Semiconductor stocks setting up: https://x.com/i/web/status/2067947769109590044
- Taiwan chip resistor price hike story: https://x.com/i/web/status/2068158302035611724
- Solar sector thesis tied to AI power demand: https://x.com/i/web/status/2068050668913647884

Leader scan and market discipline:

- Forty-eight leading names above high dollar-volume threshold: https://x.com/i/web/status/2068133234836451818
- Strongest industry groups by 1-month RS: https://x.com/i/web/status/2067883305132048757
- 8-week moving-average patience comment: https://x.com/i/web/status/2067935807957061710
- PENG high-tight-flag example: https://x.com/i/web/status/2067644861688185128
- Breakout edge needs a trending market: https://x.com/i/web/status/2067598177495105746
- Market direction, sector, group, then strongest names: https://x.com/i/web/status/2067579365487980652

Process and journaling:

- Darvas trade-rating / journal review: https://x.com/i/web/status/2067892906397208894
- Position management, stops, and alerts: https://x.com/i/web/status/2067855818368639042
- Study setups before and after: https://x.com/i/web/status/2068067382791213537

Options/social catalyst examples:

- MU call outcome: https://x.com/i/web/status/2067644802246533353
- NVDA call activity: https://x.com/i/web/status/2067675921583092025
- MU unusual call flow: https://x.com/i/web/status/2067609899668742578
- SPY dark-pool print: https://x.com/i/web/status/2067607021919117642

## Repo Compatibility

High compatibility areas:

- **X/Twitter ingestion exists**: `ContentSource`, `ContentItem`, and provider switching between official X API and private xui are already present.
- **Theme extraction exists**: `ThemeMention`, `ThemeCluster`, `ThemeConstituent`, and `ThemeMetrics` already model mentions, tickers, sentiment, velocity, basket returns, RS vs SPY, breadth, and Minervini pass counts.
- **Scan rows already carry the needed confirmation fields**: RS, RS sparkline, price sparkline, group rank, market themes, Setup Engine, Minervini/CANSLIM/IPO/Volume scores, liquidity, fundamentals, and market identity.
- **UI surfaces already exist**: Themes page, Theme Detail modal, Scan table, Stock Detail page, Market Scan dashboard, Watchlists tab, and Market Health & Exposure card.
- **Workflow hooks exist**: Add-to-watchlist menu, custom scan symbol input, stock detail route, and assistant/digest surfaces.

Friction points:

- Social items currently become theme content, not a first-class ranked ticker queue.
- `ContentItem` does not store engagement metrics today, so list engagement would need either metadata JSON or a small side table if it becomes a ranking factor.
- Real options flow is not in the repo. Posts can be extracted as social evidence, but verified flow requires a licensed/provider integration.
- Trade journaling would require new user-owned state beyond watchlist notes.

## Feature Assessment Matrix

| Rank | Feature | Compatibility | Utility | Effort | Recommendation |
| ---: | --- | --- | --- | --- | --- |
| 1 | Social Signal Queue | Very high | Very high | Medium | Build first. It connects X list signals to existing scan confirmation. |
| 2 | Theme Pulse / Rotation Evidence Panel | Very high | High | Low-Medium | Add to Themes and Daily Snapshot. Mostly UI/query work. |
| 3 | Runner Guardrails in Watchlists | High | High | Medium | Add 8/10/20/50-week or daily MA guardrails, extension, and stop notes. |
| 4 | Market Exposure Action Overlay | Very high | High | Low-Medium | Continue existing branch; use it as the gate for new buys vs hold runners. |
| 5 | Theme Basket Performance | High | High | Medium | Build on `ThemeMetrics` basket returns and constituents. |
| 6 | Scan Snapshot Journal | Medium | Medium-High | Medium-High | Useful for serious traders, but requires new user workflow and persistence. |
| 7 | Options Flow Badges | Low-Medium | Medium-High | High | Defer unless a real data provider is chosen. Social-only extraction is noisy. |

## Recommended Feature Details

### 1. Social Signal Queue

Core job: "What is the list talking about that is also technically actionable?"

Inputs:

- X list source, cashtags, extracted themes, post recency, engagement, source quality.
- Existing scan/result fields: RS rating, group rank, `market_themes`, `se_setup_score`, `se_setup_ready`, pivot distance, volume vs 50d, dollar volume, 52-week high proximity, Minervini/CANSLIM scores.
- Existing market exposure score as a risk gate.

Ranking sketch:

```text
social_signal_score =
  0.30 * mention_velocity
+ 0.20 * unique_source_count
+ 0.15 * engagement_percentile
+ 0.20 * technical_confirmation
+ 0.10 * theme_strength
+ 0.05 * recency
```

UI:

- Dashboard card with top 10 socially confirmed leaders.
- Full table tab under Themes or Scan.
- Row actions: open stock detail, open setup drawer, scan same symbols, add to watchlist.
- Evidence drawer: recent posts, extracted themes, scan confirmation, disconfirming flags.

Implementation:

- Add list source support if not already accepted in source management UI (`x.com/i/lists/<id>` already parses in backend provider).
- Preserve tweet engagement metadata via `ContentItem` metadata or a new `SocialContentMetric` table.
- Query aggregation endpoint: by ticker and date window.
- Frontend table using existing MUI/TanStack patterns.

### 2. Theme Pulse / Rotation Evidence Panel

Core job: "Which themes have both rising social attention and price leadership?"

This is nearly an extension of existing Themes:

- Add "Evidence" columns: top recent mentions, mention velocity, top cashtags, leading constituents, group rank movement.
- Add "Price confirms chatter" / "Chatter without price" badges.
- Link to RRG/group pages when an industry cluster is visible.

Best placement:

- Themes page grouped view.
- Daily Snapshot as a compact "Social x RS themes" panel.
- Stock detail as "why this stock is in the theme".

### 3. Runner Guardrails in Watchlists

Core job: "Help me hold leaders while respecting objective sell rules."

Signals from posts:

- Hold winners longer, but monitor the basket carefully.
- Use 8/10-week or 10/20-day moving averages.
- Keep stops/alerts around important levels.

Implementation:

- Add computed guardrail fields to watchlist rows: distance to 10-day, 20-day, 50-day, 10-week, 8-week approximations where available; recent close below guardrail; extension from pivot.
- Use existing `WatchlistItem.notes` initially for user rationale.
- Later add structured `entry_price`, `stop_price`, `risk_notes`, and `setup_snapshot_id`.

### 4. Options Flow Badges

Treat as a future integration, not the first build.

Low-effort version:

- Extract social evidence only, e.g. "options-flow mentioned in 4 posts today."

High-quality version:

- Add provider-backed unusual-options/dark-pool data, with licensing, normalization, ticker mapping, and timestamps.

Recommendation:

- Do not make options flow a core ranking factor until verified data exists.

## Minimal Vertical Slice

1. Seed a `ContentSource` for `https://x.com/i/lists/1522014550211457024` with high priority and technical pipeline only.
2. Ingest 30-day lookback through configured X provider.
3. Persist engagement/source metadata for X posts.
4. Build `/api/v1/social/signals` returning ticker aggregates:
   - ticker, mention_count_1d/7d/30d
   - top_theme_names
   - top_recent_posts
   - engagement score
   - scan confirmation fields joined from latest scan/feature snapshot
5. Add `SocialSignalQueue` component:
   - compact dashboard card
   - full table view
   - evidence drawer
6. Tests:
   - ingestion dedupe with list URLs
   - aggregate query fixtures
   - frontend table rendering and row actions

## Why This Should Work For Users

Minervini/StockBee/Qullamaggie style users do not want a raw social feed. They want a short list of liquid leaders where social attention, theme strength, market health, and technical setup all line up. The repo already computes most of the hard confirmation work. The feature should therefore use social as a discovery and evidence layer, not as a replacement for the scanner.

## Non-Goals

- Do not auto-trade.
- Do not rank solely by social engagement.
- Do not claim options-flow verification without a provider.
- Do not make X the only source; the same aggregation should work for RSS/news later.
