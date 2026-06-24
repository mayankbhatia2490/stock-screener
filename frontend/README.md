# Stock Scanner Frontend

React 18 SPA for stock screening, market analysis, assistant workflows, and portfolio tracking.

> Full project overview and screenshots: [Root README](../README.md)
> Backend docs: [Backend README](../backend/README.md)
> Development setup: [Development Guide](../docs/DEVELOPMENT.md)

## Setup

```bash
npm install        # Install dependencies
npm run dev        # Development server on :5173
npm run build      # Production build
npm run lint       # ESLint
```

Requires backend API running on port 8000. See [Backend README](../backend/README.md) for setup.

## Tech Stack

| Library | Purpose |
|---------|---------|
| React 18 | UI framework |
| Vite | Build tool and dev server |
| Material-UI (MUI) | Component library |
| TanStack Query | Server state management and data fetching |
| TanStack Table | Headless table with sorting, filtering, column visibility |
| TanStack Virtual | Row virtualization for large datasets |
| lightweight-charts | TradingView-style candlestick charts |
| Recharts | Area charts, sparklines, breadth visualizations |
| @hello-pangea/dnd | Drag-and-drop (watchlist ordering, folders) |
| react-markdown | Markdown rendering in assistant responses |
| axios | HTTP client |
| react-router-dom | Client-side routing |
| date-fns | Date formatting and manipulation |

## Pages

| Route | Component | Loading | Description |
|-------|-----------|---------|-------------|
| `/` | `MarketScanPage` | Lazy | Market dashboard with Daily Snapshot, Key Markets, optional Themes, Watchlists, and Stockbee MM tabs |
| `/scan` | `ScanPage` | Lazy | Multi-screener scanning with 80+ filters and CSV export |
| `/breadth` | `BreadthPage` | Lazy | StockBee-style breadth indicators and trends |
| `/groups` | `GroupRankingsPage` | Lazy | IBD industry group rankings with movers |
| `/validation` | `ValidationPage` | Lazy | Deterministic validation for scan picks and theme alerts |
| `/themes` | `ThemesPage` | Lazy | Feature-gated theme discovery with trending/emerging detection |
| `/chatbot` | `ChatbotPage` | Lazy | Feature-gated Hermes-backed assistant with streaming, citations, and watchlist actions |
| `/stocks/:ticker` | `StockDetails` | Lazy | Individual stock analysis with charts, fundamentals, themes, and validation history |
| `/operations` | `OperationsPage` | Lazy | Runtime activity, telemetry alerts, queue/job inventory, and safe job controls |

Canonical route/user-flow documentation lives in the [Live App Guide](../docs/LIVE_APP_GUIDE.md).

## Project Structure

```
src/
├── main.jsx                     # App entry point
├── App.jsx                      # Router, theme, providers
├── index.css                    # Global styles
├── api/                         # API client modules (one per backend group)
│   ├── client.js                #   Axios instance with baseURL
│   ├── scans.js                 #   Scan operations
│   ├── stocks.js                #   Stock data
│   ├── breadth.js               #   Market breadth
│   ├── groups.js                #   Group rankings
│   ├── themes.js                #   Theme discovery
│   ├── assistant.js             #   Assistant sessions/messages
│   ├── validation.js            #   Backtest/validation overview
│   ├── operations.js            #   Operations job console
│   ├── telemetry.js             #   Runtime telemetry alerts
│   ├── userWatchlists.js        #   Watchlist CRUD
│   ├── userThemes.js            #   User themes
│   ├── marketScan.js            #   Dashboard scan lists
│   ├── filterPresets.js         #   Saved filter configs
│   ├── priceHistory.js          #   Price/chart data
│   ├── tasks.js                 #   Background task polling
│   └── cache.js                 #   Cache management
├── pages/                       # Top-level page components
│   ├── ScanPage.jsx             #   Bulk scanner
│   ├── MarketScanPage.jsx       #   Market dashboard (home)
│   ├── BreadthPage.jsx          #   Market breadth
│   ├── GroupRankingsPage.jsx    #   Group rankings
│   ├── ValidationPage.jsx       #   Backtest/validation
│   ├── ThemesPage.jsx           #   Theme discovery
│   ├── ChatbotPage.jsx          #   Assistant page route
│   └── OperationsPage.jsx       #   Runtime operations console
├── components/                  # Shared and feature components
│   ├── Layout/                  #   App shell, navigation
│   ├── Scan/                    #   Scanner UI (filters, results table)
│   ├── MarketScan/              #   Dashboard cards, watchlist table
│   ├── Stock/                   #   StockDetails view
│   ├── Charts/                  #   Chart modal, candlestick charts
│   ├── AssistantChat/           #   Assistant interface and message rendering
│   ├── Themes/                  #   Theme rankings, emerging panel
│   ├── Technical/               #   Technical indicator displays
│   ├── Settings/                #   App settings
│   ├── common/                  #   Reusable UI primitives
│   └── PipelineProgressCard.jsx #   Scan progress indicator
├── contexts/                    # React contexts
│   ├── RuntimeContext.jsx       #   Auth, bootstrap, capabilities, runtime markets
│   ├── MarketContext.jsx        #   Active market selection
│   ├── StrategyProfileContext.jsx #   Strategy profile defaults
│   ├── PipelineContext.jsx      #   Theme/scan pipeline progress state
│   ├── AssistantChatContext.jsx #   Assistant sessions and messages
│   └── ColorModeContext.js      #   Dark/light mode state
├── hooks/                       # Custom hooks
│   ├── useChartNavigation.js    #   Keyboard nav for chart modal
│   ├── useFilterPresets.js      #   Filter preset CRUD
│   └── ...                      #   Additional feature hooks
├── config/                      # Static configuration
│   └── runtimeMode.js           #   Static export mode flags
└── utils/                       # Pure utility functions
    ├── colorUtils.js            #   Color calculations
    ├── filterUtils.js           #   Filter logic helpers
    └── formatUtils.js           #   Number/date formatting
```

## API Client Convention

The axios client in `api/client.js` sets `baseURL` to include the `/api` prefix:
- **Local dev**: `baseURL = 'http://localhost:8000/api'`
- **Docker**: `baseURL = '/api'` (set via `VITE_API_URL` build arg)

All API paths must start with `/v1/...`, never `/api/v1/...`:

```javascript
// CORRECT — path without /api prefix
const response = await apiClient.get('/v1/themes/rankings');

// WRONG — double prefix in Docker: /api/api/v1/...
const response = await apiClient.get('/api/v1/themes/rankings');
```

For modules with a `BASE_PATH` constant, same rule:

```javascript
const BASE_PATH = '/v1/user-themes';     // correct
const BASE_PATH = '/api/v1/user-themes'; // wrong
```

## Patterns

### Data Fetching

TanStack Query with 5-minute stale time and `placeholderData` for smooth transitions between loading states. Cache time is 30 minutes. Configured once in `App.jsx`.

### Theming

Dark mode by default. Dense 24px table rows. Compact 11-14px typography. Light mode supported via `ColorModeContext` toggle. Theme tokens defined in `App.jsx` → `getDesignTokens()`.

### Code Splitting

Live pages, auth screens, bootstrap setup, and the static shell are loaded with `React.lazy()` and wrapped in `<Suspense>`. This keeps the initial bundle free of heavy page-specific chart and dashboard chunks.

### State Management

No global store. TanStack Query handles server state, `useState` handles local UI state, and scoped contexts cover runtime capabilities/auth/bootstrap, active market, strategy profile defaults, pipeline progress, assistant chat state, and dark/light mode.

### Adding a Page

1. Create component in `pages/`
2. Add route in `App.jsx` (eager import or `React.lazy()`)
3. Add navigation item in `components/Layout/`
4. Create API module in `api/` if new endpoints are needed

### Adding an API Endpoint

1. Create or update module in `api/` (e.g., `api/myFeature.js`)
2. Import and use `apiClient` from `api/client.js`
3. Use `/v1/...` paths (never `/api/v1/...`)
