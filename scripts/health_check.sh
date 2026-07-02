#!/bin/bash
# Comprehensive health check for stock-screener on Synology DS220+
# Run from ~/stock-screener on the NAS:
#   bash scripts/health_check.sh

set -euo pipefail

API="http://localhost:7777/api/v1"
PASS=0
FAIL=0
WARN=0

green()  { echo -e "\033[32m[PASS]\033[0m $*"; PASS=$((PASS+1)); }
red()    { echo -e "\033[31m[FAIL]\033[0m $*"; FAIL=$((FAIL+1)); }
yellow() { echo -e "\033[33m[WARN]\033[0m $*"; WARN=$((WARN+1)); }
header() { echo; echo -e "\033[1m=== $* ===\033[0m"; }

# ── 1. DOCKER CONTAINERS ──────────────────────────────────────────────────────
header "1. Docker containers"

REQUIRED_CONTAINERS=(
  "stock-screener-backend-1"
  "stock-screener-postgres-1"
  "stock-screener-redis-1"
  "stock-screener-frontend-1"
  "stock-screener-celery-beat-1"
  "stock-screener-celery-general-1"
  "stock-screener-celery-datafetch-1"
  "stock-screener-celery-marketjobs-us-1"
)

for c in "${REQUIRED_CONTAINERS[@]}"; do
  STATUS=$(docker inspect "$c" --format '{{.State.Status}}' 2>/dev/null || echo "missing")
  HEALTH=$(docker inspect "$c" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' 2>/dev/null || echo "n/a")
  if [ "$STATUS" = "running" ]; then
    if [ "$HEALTH" = "unhealthy" ]; then
      red "$c — running but UNHEALTHY"
    else
      green "$c — $STATUS ($HEALTH)"
    fi
  else
    red "$c — $STATUS"
  fi
done

# ── 2. BACKEND HEALTH ─────────────────────────────────────────────────────────
header "2. Backend health endpoint"

READYZ=$(curl -sf http://localhost:7777/readyz 2>/dev/null || curl -sf http://localhost:8000/readyz 2>/dev/null || echo "ERROR")
if echo "$READYZ" | grep -q '"status"'; then
  DB=$(echo "$READYZ" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('database','?'))" 2>/dev/null || echo "?")
  REDIS=$(echo "$READYZ" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('redis','?'))" 2>/dev/null || echo "?")
  green "Backend /readyz — database=$DB  redis=$REDIS"
else
  red "Backend /readyz unreachable or returned error"
fi

# ── 3. PRICE CACHE STATUS ─────────────────────────────────────────────────────
header "3. Price cache & data freshness"

CACHE_STATUS=$(curl -sf "$API/cache/market-status" 2>/dev/null || echo "ERROR")
if [ "$CACHE_STATUS" = "ERROR" ]; then
  red "Cache market-status endpoint unreachable"
else
  OVERALL=$(echo "$CACHE_STATUS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('overall_status', d.get('status', 'unknown')))
" 2>/dev/null || echo "unknown")
  LAST=$(echo "$CACHE_STATUS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('last_refreshed_trading_day', d.get('last_refresh', 'unknown')))
" 2>/dev/null || echo "unknown")
  if echo "$OVERALL" | grep -qi "ok\|completed\|fresh"; then
    green "Price cache — status=$OVERALL  last_refreshed=$LAST"
  else
    yellow "Price cache — status=$OVERALL  last_refreshed=$LAST (run pipeline to refresh)"
  fi
fi

STALENESS=$(curl -sf "$API/cache/staleness-status" 2>/dev/null || echo "ERROR")
if [ "$STALENESS" != "ERROR" ]; then
  IS_STALE=$(echo "$STALENESS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('is_stale', d.get('stale', 'unknown')))
" 2>/dev/null || echo "unknown")
  STALE_COUNT=$(echo "$STALENESS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('stale_count', d.get('stale_symbols', '?')))
" 2>/dev/null || echo "?")
  if [ "$IS_STALE" = "False" ] || [ "$IS_STALE" = "false" ]; then
    green "Staleness check — not stale  stale_symbols=$STALE_COUNT"
  else
    yellow "Staleness check — is_stale=$IS_STALE  stale_symbols=$STALE_COUNT"
  fi
fi

# ── 4. GROUP RANKINGS ─────────────────────────────────────────────────────────
header "4. Group rankings"

GROUPS=$(curl -sf "$API/groups/rankings/current?market=US&limit=5" 2>/dev/null || echo "ERROR")
if [ "$GROUPS" = "ERROR" ]; then
  red "Group rankings endpoint unreachable"
else
  COUNT=$(echo "$GROUPS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
rankings = d.get('rankings', d.get('groups', d.get('data', [])))
print(len(rankings))
" 2>/dev/null || echo "0")
  DATE=$(echo "$GROUPS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('as_of_date', d.get('date', 'unknown')))
" 2>/dev/null || echo "unknown")
  if [ "$COUNT" -gt "0" ] 2>/dev/null; then
    green "Group rankings — $COUNT groups returned  as_of=$DATE"
  else
    yellow "Group rankings — returned 0 groups (pipeline not yet run today)"
  fi
fi

# ── 5. BREADTH DATA ───────────────────────────────────────────────────────────
header "5. Market breadth"

BREADTH=$(curl -sf "$API/breadth/current?market=US" 2>/dev/null || echo "ERROR")
if [ "$BREADTH" = "ERROR" ]; then
  red "Breadth endpoint unreachable"
else
  B_DATE=$(echo "$BREADTH" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('date', d.get('as_of_date', 'unknown')))
" 2>/dev/null || echo "unknown")
  ADV=$(echo "$BREADTH" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('advancing', d.get('adv', '?')))
" 2>/dev/null || echo "?")
  if [ "$B_DATE" != "unknown" ] && [ "$B_DATE" != "null" ]; then
    green "Breadth data — date=$B_DATE  advancing=$ADV"
  else
    yellow "Breadth data — no data yet (pipeline not yet run)"
  fi
fi

# ── 6. MARKET SCAN / DAILY SNAPSHOT ──────────────────────────────────────────
header "6. Market scan snapshot"

SNAPSHOT=$(curl -sf "$API/market-scan/daily-snapshot?market=US" 2>/dev/null || echo "ERROR")
if [ "$SNAPSHOT" = "ERROR" ]; then
  red "Market scan snapshot unreachable"
else
  SNAP_DATE=$(echo "$SNAPSHOT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('as_of_date', d.get('date', d.get('meta', {}).get('as_of_date', 'unknown'))))
" 2>/dev/null || echo "unknown")
  STOCK_COUNT=$(echo "$SNAPSHOT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d.get('rows', d.get('stocks', d.get('data', [])))
print(len(rows))
" 2>/dev/null || echo "0")
  if [ "$STOCK_COUNT" -gt "0" ] 2>/dev/null; then
    green "Market snapshot — $STOCK_COUNT stocks  as_of=$SNAP_DATE"
  else
    yellow "Market snapshot — 0 stocks returned (pipeline not yet run today)"
  fi
fi

# ── 7. PIPELINE / RUNTIME ACTIVITY ───────────────────────────────────────────
header "7. Pipeline activity status"

ACTIVITY=$(curl -sf "$API/runtime/activity" 2>/dev/null || echo "ERROR")
if [ "$ACTIVITY" = "ERROR" ]; then
  red "Runtime activity endpoint unreachable"
else
  SUMMARY_STATUS=$(echo "$ACTIVITY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('summary', {}).get('status', 'unknown'))
" 2>/dev/null || echo "unknown")
  MARKET_STATUS=$(echo "$ACTIVITY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
markets = d.get('markets', [])
us = next((m for m in markets if m.get('market') == 'US'), {})
print(us.get('status', 'no US market entry'))
" 2>/dev/null || echo "unknown")
  STAGE=$(echo "$ACTIVITY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
markets = d.get('markets', [])
us = next((m for m in markets if m.get('market') == 'US'), {})
print(us.get('stage_key', us.get('message', '-')))
" 2>/dev/null || echo "-")
  if echo "$SUMMARY_STATUS" | grep -qi "idle\|ok\|completed"; then
    green "Runtime activity — summary=$SUMMARY_STATUS  US=$MARKET_STATUS  stage=$STAGE"
  elif echo "$SUMMARY_STATUS" | grep -qi "running"; then
    yellow "Runtime activity — RUNNING  US=$MARKET_STATUS  stage=$STAGE"
  else
    yellow "Runtime activity — summary=$SUMMARY_STATUS  US=$MARKET_STATUS  stage=$STAGE"
  fi
fi

# ── 8. CELERY WORKERS VIA DB CHECK ───────────────────────────────────────────
header "8. Scheduled tasks (celery-beat)"

BEAT_LOGS=$(docker logs stock-screener-celery-beat-1 2>&1 | grep -E "Scheduler|daily|pipeline|beat" | tail -5)
if [ -n "$BEAT_LOGS" ]; then
  green "celery-beat active — recent log:"
  echo "$BEAT_LOGS" | sed 's/^/    /'
else
  yellow "celery-beat — no recent scheduler log lines found"
fi

# ── 9. DATABASE KEY DATA ─────────────────────────────────────────────────────
header "9. Database checks"

# Active symbols count
ACTIVE=$(docker exec stock-screener-postgres-1 psql -U stockscanner stockscanner -t -c \
  "SELECT COUNT(*) FROM stock_universe WHERE is_active=true AND market='US';" 2>/dev/null | tr -d ' ')
if [ -n "$ACTIVE" ] && [ "$ACTIVE" -gt "0" ] 2>/dev/null; then
  green "Active US symbols in universe: $ACTIVE"
else
  red "Active US symbols: $ACTIVE (expected > 0)"
fi

# Latest price date
LATEST_PRICE=$(docker exec stock-screener-postgres-1 psql -U stockscanner stockscanner -t -c \
  "SELECT MAX(date) FROM stock_prices sp JOIN stock_universe su ON sp.symbol=su.symbol WHERE su.market='US' AND su.is_active=true;" 2>/dev/null | tr -d ' ')
if [ -n "$LATEST_PRICE" ]; then
  green "Latest price date in DB: $LATEST_PRICE"
else
  yellow "Could not determine latest price date"
fi

# Alembic migration version
MIGRATION=$(docker exec stock-screener-postgres-1 psql -U stockscanner stockscanner -t -c \
  "SELECT version_num FROM alembic_version;" 2>/dev/null | tr -d ' ' | sort | tail -1)
green "DB migration revision: $MIGRATION"

# Market refresh state
REFRESH_STATE=$(docker exec stock-screener-postgres-1 psql -U stockscanner stockscanner -t -c \
  "SELECT value FROM app_settings WHERE key='market.refresh_state.US';" 2>/dev/null | tr -d ' ')
if [ -n "$REFRESH_STATE" ]; then
  REFRESH_DATE=$(echo "$REFRESH_STATE" | python3 -c "
import sys, json
d = json.loads(sys.stdin.read().strip())
print(d.get('last_refreshed_trading_day','?') + '  status=' + d.get('status','?'))
" 2>/dev/null || echo "$REFRESH_STATE")
  green "Last price refresh: $REFRESH_DATE"
else
  yellow "No market refresh state recorded yet"
fi

# ── SUMMARY ───────────────────────────────────────────────────────────────────
header "SUMMARY"
echo -e "\033[32mPASS: $PASS\033[0m  \033[33mWARN: $WARN\033[0m  \033[31mFAIL: $FAIL\033[0m"
echo
if [ "$FAIL" -gt "0" ]; then
  echo "Action required: fix FAIL items above before the nightly pipeline runs."
elif [ "$WARN" -gt "0" ]; then
  echo "System healthy. WARN items will resolve after tonight's pipeline run (00:30 UAE)."
else
  echo "All checks passed. System is fully operational."
fi
