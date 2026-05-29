import {
  TEST_SYMBOLS,
  UNIVERSE_GEOGRAPHIC_MARKETS,
  UNIVERSE_MARKETS,
  UNIVERSE_SCOPES_BY_MARKET,
} from './constants';

const SCAN_BLOCKING_ACTIVITY_STAGES = new Set(['prices', 'fundamentals']);
const SCAN_BLOCKING_ACTIVITY_STATUSES = new Set(['queued', 'running']);

function normalizeMarket(value) {
  return value ? String(value).trim().toUpperCase() : null;
}

function hasRuntimeUniverseOptions(universeOptions) {
  return Array.isArray(universeOptions?.markets) && universeOptions.markets.length > 0;
}

function fallbackUniverseSelections() {
  return {
    markets: UNIVERSE_MARKETS.map((option) => ({
      ...option,
      disabled: false,
      disabledReason: null,
    })),
    scopesByMarket: Object.fromEntries(
      Object.entries(UNIVERSE_SCOPES_BY_MARKET).map(([market, options]) => [
        market,
        options.map((option) => ({
          ...option,
          disabled: false,
          disabledReason: null,
        })),
      ])
    ),
  };
}

function runtimeScopeOption(option, extras = {}) {
  return {
    value: option.value,
    label: option.label,
    universe_def: option.universe_def,
    aliases: option.aliases ?? [],
    disabled: false,
    disabledReason: null,
    ...extras,
  };
}

export function getMarketScanBlocker(activity, market) {
  const marketCode = normalizeMarket(market);
  if (!marketCode || marketCode === 'TEST') {
    return null;
  }
  const marketActivity = (activity?.markets ?? []).find((item) => (
    normalizeMarket(item?.market) === marketCode
    && SCAN_BLOCKING_ACTIVITY_STAGES.has(item.stage_key)
    && SCAN_BLOCKING_ACTIVITY_STATUSES.has(item.status)
  ));
  if (!marketActivity) {
    return null;
  }
  const stageLabel = marketActivity.stage_label || marketActivity.stage_key || 'Refresh';
  const status = marketActivity.status === 'queued' ? 'queued' : 'running';
  return {
    market: marketCode,
    stageKey: marketActivity.stage_key,
    stageLabel,
    status,
    lifecycle: marketActivity.lifecycle ?? null,
    message: `${marketCode} ${stageLabel.toLowerCase()} is ${status}. Wait for it to finish before starting a scan.`,
  };
}

export function buildRuntimeUniverseSelections(universeOptions, runtimeActivity = null) {
  if (!hasRuntimeUniverseOptions(universeOptions)) {
    return fallbackUniverseSelections();
  }

  const scopesByMarket = {};
  const markets = universeOptions.markets.map((marketOption) => {
    const market = normalizeMarket(marketOption.code);
    const blocker = getMarketScanBlocker(runtimeActivity, market);
    const notEnabled = marketOption.enabled === false;
    const disabled = notEnabled || Boolean(blocker);
    const disabledReason = notEnabled
      ? 'Not enabled'
      : blocker
        ? `${blocker.stageLabel} ${blocker.status}`
        : null;
    const disabledState = { disabled, disabledReason };

    const scopes = [];
    if (marketOption.market) {
      scopes.push(runtimeScopeOption(marketOption.market, { kind: 'market', ...disabledState }));
    }
    for (const mic of marketOption.mics ?? []) {
      scopes.push(runtimeScopeOption(mic, {
        kind: 'mic',
        mic: mic.mic,
        ...disabledState,
      }));
    }
    for (const index of marketOption.indexes ?? []) {
      scopes.push(runtimeScopeOption(index, {
        kind: 'index',
        key: index.key,
        ...disabledState,
      }));
    }
    for (const tier of marketOption.listing_tiers ?? []) {
      scopes.push(runtimeScopeOption(tier, {
        kind: 'listing_tier',
        key: tier.key,
        mic: tier.mic,
        ...disabledState,
      }));
    }
    scopesByMarket[market] = scopes;

    return {
      value: market,
      label: marketOption.label,
      disabled,
      disabledReason,
    };
  });

  markets.push({ value: 'TEST', label: 'Test Mode', disabled: false, disabledReason: null });
  scopesByMarket.TEST = [];
  return { markets, scopesByMarket };
}

function findRuntimeScopeOption(market, scope, universeOptionsOrSelections) {
  const selections = universeOptionsOrSelections?.scopesByMarket
    ? universeOptionsOrSelections
    : buildRuntimeUniverseSelections(universeOptionsOrSelections);
  return selections.scopesByMarket?.[market]?.find((option) => option.value === scope) ?? null;
}

export function resolveUniverseScopeValue(market, scope, universeSelections) {
  if (!market || !scope) {
    return scope ?? null;
  }
  const options = universeSelections?.scopesByMarket?.[market] ?? [];
  if (options.some((option) => option.value === scope)) {
    return scope;
  }
  if (scope === 'market') {
    return options.find((option) => (
      option.universe_def?.type === 'market'
      && option.universe_def?.market === market
      && !option.universe_def?.mic
      && !option.universe_def?.listing_tier
    ))?.value ?? scope;
  }
  if (scope.startsWith('index:')) {
    const index = scope.slice('index:'.length);
    return options.find((option) => option.universe_def?.index === index)?.value ?? scope;
  }
  if (scope.startsWith('exchange:')) {
    const exchange = scope.slice('exchange:'.length).toUpperCase();
    return options.find((option) => (
      option.mic === exchange
      || option.universe_def?.mic === exchange
      || option.aliases?.includes(exchange)
      || option.universe_def?.exchange === exchange
    ))?.value ?? scope;
  }
  return scope;
}

// Build a typed universe_def payload from the two-step picker state.
// Returns null when the selection is incomplete (caller should disable submit).
export function buildUniverseDef(market, scope, universeOptionsOrSelections = null) {
  if (market === 'TEST') {
    return { type: 'test', symbols: TEST_SYMBOLS };
  }
  if (!market || !scope) {
    return null;
  }
  const runtimeOption = findRuntimeScopeOption(market, scope, universeOptionsOrSelections);
  if (runtimeOption?.universe_def) {
    return runtimeOption.universe_def;
  }
  if (scope === 'market') {
    return { type: 'market', market };
  }
  if (scope.startsWith('exchange:')) {
    return { type: 'exchange', market, exchange: scope.slice('exchange:'.length) };
  }
  if (scope.startsWith('index:')) {
    return { type: 'index', index: scope.slice('index:'.length) };
  }
  return null;
}

// Count of stocks matching a (market, scope) selection, derived from the
// universeStats bootstrap payload. Returns null when data isn't available yet.
export function getSelectionCount(market, scope, universeStats, runtimeUniverseDef = null) {
  if (!universeStats) {
    return null;
  }
  if (market === 'TEST') {
    return TEST_SYMBOLS.length;
  }
  if (!market || !scope) {
    return null;
  }
  const universeDef = runtimeUniverseDef?.universe_def ?? runtimeUniverseDef;
  if (universeDef?.type === 'market') {
    if (universeDef.listing_tier) {
      return null;
    }
    if (universeDef.mic) {
      return universeStats.by_exchange?.[universeDef.mic] ?? null;
    }
    return universeStats.by_market?.[universeDef.market]?.counts?.active ?? null;
  }
  if (universeDef?.type === 'index') {
    return universeDef.index === 'SP500' ? universeStats.sp500 ?? null : null;
  }
  if (scope === 'market') {
    return universeStats.by_market?.[market]?.counts?.active ?? null;
  }
  if (scope.startsWith('exchange:')) {
    const exchange = scope.slice('exchange:'.length);
    return universeStats.by_exchange?.[exchange] ?? null;
  }
  if (scope === 'index:SP500') {
    return universeStats.sp500 ?? null;
  }
  return null;
}

// Map a legacy saved-default string (e.g. 'nyse', 'sp500', 'market:hk') to the
// new (market, scope) picker state. Ambiguous 'all' yields (null, null) so
// users must explicitly pick a market, matching the bead's design intent.
export function parseLegacyUniverseDefault(legacy) {
  if (typeof legacy !== 'string') {
    return { market: null, scope: null };
  }
  const value = legacy.trim().toLowerCase();
  if (value === 'test') {
    return { market: 'TEST', scope: null };
  }
  if (value === 'nyse' || value === 'nasdaq' || value === 'amex') {
    return { market: 'US', scope: `exchange:${value.toUpperCase()}` };
  }
  if (value === 'sp500') {
    return { market: 'US', scope: 'index:SP500' };
  }
  if (value.startsWith('market:')) {
    const market = value.slice('market:'.length).toUpperCase();
    if (UNIVERSE_GEOGRAPHIC_MARKETS.includes(market)) {
      return { market, scope: 'market' };
    }
  }
  return { market: null, scope: null };
}
