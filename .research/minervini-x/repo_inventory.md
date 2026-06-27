# Repo Feature Inventory (xang1234/stock-screener == /Users/admin/StockScreenClaude)

## Screeners (backend/app/scanners/)
- Minervini Template: RS>70, MA alignment 50>150>200, Stage 2, VCP, dist to 52wk hi/lo
- CANSLIM: quarterly+annual EPS growth, new highs, volume, RS, institutional 40-70%
- IPO Scanner: IPO age 6mo-2yr, post-IPO strength, revenue growth
- Volume Breakthrough: 5yr/1yr/since-IPO volume highs, 5-day time-decay scoring
- Setup Engine Scanner: full pattern pipeline + readiness + calibration
- Custom Scanner: 13+ configurable filters

## Signals / Detectors (backend/app/analysis/patterns/)
- Patterns: Cup-with-Handle, VCP, Double Bottom, Three Weeks Tight, High Tight Flag, First Pullback, NR7/Inside Day
- Base detector taxonomy: DETECTED|NOT_DETECTED|INSUFFICIENT_DATA|NOT_IMPLEMENTED|ERROR
- Technicals: Bollinger width/percentile/squeeze, ATR14, new-high detection, quiet days, up/down vol ratio
- RS Line (rs_line.py): RS line vs benchmark, "blue dot" (RS new high before price), normalized overlay, 252d
- Readiness: distance to pivot, ATR% of price, BB squeeze, vol vs 50d, RS vs SPY 65d/20d trend

## Market Analysis
- Breadth (breadth_calculator_service): daily 4% movers up/down, 5d/10d ratios, 25%/50% movers (21/63d), 34-day 13% movers, net 4%
- Market Exposure (market_exposure_service): 0-100 exposure score; trend (50/200 DMA), distribution days (25-session), FOLLOW-THROUGH DAY (1.5%+ up, 15-session lookback), VIX (US), breadth, golden/death cross; Bullish/Neutral/Bearish bands; 220-day backfill
- IBD Group Rankings: 197 groups by RS, movers 1W/1M/3M/6M, rank history
- RRG (rrg_service): RS-Ratio vs RS-Momentum quadrants, weekly path arrows, per-market

## Indicators & Metrics (technical_calculator_service)
- RSI14, ATR14, volatility weekly/monthly, SMA 20/50/200, EMA 10/20/50, price vs MA
- Performance: 5d/21d/63d/126d/252d/YTD; 52wk hi/lo + % below/above
- Volume: 50d avg, relative volume; Bollinger 20/2 + squeeze
- RS Rating 1m/3m/12m (0-100), beta-adjusted RS, RS sparklines, RS trend -1/0/1
- Growth/valuation: EPS curr/nextQ/next5Y, EPS growth QoQ/YoY, sales growth, PEG/PE/PB/PS/fwdPE, EPS Rating 0-99
- Price: gap%, volume surge >=2x, Pocket Pivot, Power Trend, ADR%
- Multi-period (Qullamaggie): 1d/5d/21d/67d(>=50%)/126d(>=150%)

## Data Available
- 5yr OHLCV cached (Redis 7d TTL), stock_prices table
- Fundamentals: mktcap, shares, valuation ratios, EPS/revenue growth, margins, ROE/ROA/ROIC, current/quick ratio, debt, insider %, institutional %, short float, beta, RSI/ATR/SMA stored, quarterly reporting metadata
- Markets: US, HK, IN, JP, KR, TW, CN, DE, CA, SG, MY, AU (12) with per-market calendars + benchmarks
- Benchmarks: SPY/QQQ (US), ^HSI, ^N225, etc.
- Universe: S&P500, Russell3000, Nasdaq100, official exchange lists

## Frontend Pages (frontend/src/pages/)
- ScanPage (80+ filters, results table, CSV), BreadthPage (SPY overlay), GroupRankingsPage (+RRG), ThemesPage, ChatbotPage (research mode), DigestPage, OperationsPage, ValidationPage, MarketScanPage
- Components: BreadthChart, RRGChart, PriceChart/CandlestickChart, SetupEngineDrawer, MarketHealthExposure (FTD markers), ResultsTable (sparklines, badges), watchlists

## Known gaps (per explorer)
- Pocket Pivot refinement, Episodic Pivot confirmed detection, options flow, sector rotation heatmaps beyond RRG, custom alert rules (UI only), ML classifiers (SE is rule-based)
