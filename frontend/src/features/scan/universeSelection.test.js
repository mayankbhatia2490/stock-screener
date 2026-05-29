import { describe, expect, it } from 'vitest';

import { TEST_SYMBOLS, UNIVERSE_SCOPES_BY_MARKET } from './constants';
import {
  buildUniverseDef,
  buildRuntimeUniverseSelections,
  getSelectionCount,
  parseLegacyUniverseDefault,
  resolveUniverseScopeValue,
} from './universeSelection';

const runtimeUniverseOptions = {
  version: 'test.v1',
  supported_markets: ['US', 'HK'],
  enabled_markets: ['US'],
  markets: [
    {
      code: 'US',
      label: 'United States',
      enabled: true,
      market: {
        value: 'market:US',
        label: 'All United States',
        universe_def: { type: 'market', market: 'US' },
      },
      mics: [
        {
          value: 'market:US:mic:XNYS',
          label: 'XNYS',
          mic: 'XNYS',
          aliases: ['NYSE'],
          universe_def: { type: 'market', market: 'US', mic: 'XNYS' },
        },
      ],
      indexes: [
        {
          value: 'index:SP500',
          label: 'S&P 500',
          key: 'SP500',
          aliases: [],
          universe_def: { type: 'index', index: 'SP500' },
        },
      ],
      listing_tiers: [],
    },
    {
      code: 'HK',
      label: 'Hong Kong',
      enabled: false,
      market: {
        value: 'market:HK',
        label: 'All Hong Kong',
        universe_def: { type: 'market', market: 'HK' },
      },
      mics: [
        {
          value: 'market:HK:mic:XHKG',
          label: 'XHKG',
          mic: 'XHKG',
          aliases: ['HKEX', 'SEHK'],
          universe_def: { type: 'market', market: 'HK', mic: 'XHKG' },
        },
      ],
      indexes: [
        {
          value: 'index:HSI',
          label: 'Hang Seng Index',
          key: 'HSI',
          aliases: [],
          universe_def: { type: 'index', index: 'HSI' },
        },
      ],
      listing_tiers: [
        {
          value: 'market:HK:mic:XHKG:tier:main_board',
          label: 'Main Board',
          key: 'main_board',
          mic: 'XHKG',
          aliases: ['MAIN'],
          universe_def: {
            type: 'market',
            market: 'HK',
            mic: 'XHKG',
            listing_tier: 'main_board',
          },
        },
      ],
    },
  ],
};

describe('buildUniverseDef', () => {
  it('returns null when market is missing', () => {
    expect(buildUniverseDef(null, 'market')).toBeNull();
  });

  it('returns null when market is set but scope is missing (non-TEST)', () => {
    expect(buildUniverseDef('US', null)).toBeNull();
  });

  it('maps TEST market to a typed test universe with the preset symbol list', () => {
    expect(buildUniverseDef('TEST', null)).toEqual({
      type: 'test',
      symbols: TEST_SYMBOLS,
    });
  });

  it('maps scope "market" to a typed market universe', () => {
    expect(buildUniverseDef('HK', 'market')).toEqual({ type: 'market', market: 'HK' });
  });

  it('maps exchange and index scopes to their typed forms', () => {
    expect(buildUniverseDef('US', 'exchange:NYSE')).toEqual({
      type: 'exchange',
      market: 'US',
      exchange: 'NYSE',
    });
    expect(buildUniverseDef('CN', 'exchange:BJSE')).toEqual({
      type: 'exchange',
      market: 'CN',
      exchange: 'BJSE',
    });
    expect(buildUniverseDef('US', 'index:SP500')).toEqual({ type: 'index', index: 'SP500' });
  });

  it('returns the backend-provided universe definition for runtime option scopes', () => {
    expect(
      buildUniverseDef('HK', 'market:HK:mic:XHKG:tier:main_board', runtimeUniverseOptions)
    ).toEqual({
      type: 'market',
      market: 'HK',
      mic: 'XHKG',
      listing_tier: 'main_board',
    });
  });
});

describe('buildRuntimeUniverseSelections', () => {
  it('builds market and universe options from runtime capabilities', () => {
    const selections = buildRuntimeUniverseSelections(runtimeUniverseOptions);

    expect(selections.markets).toEqual([
      expect.objectContaining({ value: 'US', label: 'United States', disabled: false }),
      expect.objectContaining({ value: 'HK', label: 'Hong Kong', disabled: true }),
      expect.objectContaining({ value: 'TEST', label: 'Test Mode', disabled: false }),
    ]);
    expect(selections.scopesByMarket.HK).toEqual([
      expect.objectContaining({
        value: 'market:HK',
        label: 'All Hong Kong',
        universe_def: { type: 'market', market: 'HK' },
      }),
      expect.objectContaining({
        value: 'market:HK:mic:XHKG',
        label: 'XHKG',
        universe_def: { type: 'market', market: 'HK', mic: 'XHKG' },
      }),
      expect.objectContaining({
        value: 'index:HSI',
        label: 'Hang Seng Index',
        universe_def: { type: 'index', index: 'HSI' },
      }),
      expect.objectContaining({
        value: 'market:HK:mic:XHKG:tier:main_board',
        label: 'Main Board',
        universe_def: {
          type: 'market',
          market: 'HK',
          mic: 'XHKG',
          listing_tier: 'main_board',
        },
      }),
    ]);
  });

  it('disables markets with active scan-blocking runtime activity', () => {
    const selections = buildRuntimeUniverseSelections(
      runtimeUniverseOptions,
      {
        markets: [
          {
            market: 'US',
            stage_key: 'prices',
            stage_label: 'Price Refresh',
            status: 'running',
          },
        ],
      }
    );

    expect(selections.markets.find((market) => market.value === 'US')).toEqual(
      expect.objectContaining({ disabled: true, disabledReason: 'Price Refresh running' })
    );
  });

  it('normalizes legacy default scopes to runtime option values', () => {
    const selections = buildRuntimeUniverseSelections(runtimeUniverseOptions);

    expect(resolveUniverseScopeValue('HK', 'market', selections)).toBe('market:HK');
    expect(resolveUniverseScopeValue('US', 'exchange:NYSE', selections)).toBe('market:US:mic:XNYS');
    expect(resolveUniverseScopeValue('US', 'index:SP500', selections)).toBe('index:SP500');
  });
});

describe('getSelectionCount', () => {
  const stats = {
    active: 7500,
    sp500: 500,
    by_exchange: { NYSE: 2500, NASDAQ: 3000, AMEX: 400 },
    by_market: {
      US: { counts: { active: 5900 } },
      HK: { counts: { active: 2400 } },
      CN: { counts: { active: 5492 } },
    },
  };

  it('returns null when stats are not loaded yet', () => {
    expect(getSelectionCount('US', 'market', null)).toBeNull();
  });

  it('returns the per-market active count for market scope', () => {
    expect(getSelectionCount('US', 'market', stats)).toBe(5900);
    expect(getSelectionCount('HK', 'market', stats)).toBe(2400);
    expect(getSelectionCount('CN', 'market', stats)).toBe(5492);
  });

  it('returns the by_exchange count for exchange scopes', () => {
    expect(getSelectionCount('US', 'exchange:NYSE', stats)).toBe(2500);
  });

  it('returns the sp500 count for the SP500 index', () => {
    expect(getSelectionCount('US', 'index:SP500', stats)).toBe(500);
  });

  it('returns the TEST_SYMBOLS length for TEST market', () => {
    expect(getSelectionCount('TEST', null, stats)).toBe(TEST_SYMBOLS.length);
  });

  it('returns null for a market that has no stats entry', () => {
    expect(getSelectionCount('JP', 'market', stats)).toBeNull();
  });
});

describe('parseLegacyUniverseDefault', () => {
  it('maps exchange legacy strings to US + exchange scope', () => {
    expect(parseLegacyUniverseDefault('nyse')).toEqual({
      market: 'US',
      scope: 'exchange:NYSE',
    });
    expect(parseLegacyUniverseDefault('nasdaq')).toEqual({
      market: 'US',
      scope: 'exchange:NASDAQ',
    });
  });

  it('maps sp500 to US + index scope', () => {
    expect(parseLegacyUniverseDefault('sp500')).toEqual({
      market: 'US',
      scope: 'index:SP500',
    });
  });

  it('maps market:hk and friends to market scope', () => {
    expect(parseLegacyUniverseDefault('market:hk')).toEqual({ market: 'HK', scope: 'market' });
    expect(parseLegacyUniverseDefault('market:jp')).toEqual({ market: 'JP', scope: 'market' });
    expect(parseLegacyUniverseDefault('market:kr')).toEqual({ market: 'KR', scope: 'market' });
    expect(parseLegacyUniverseDefault('market:cn')).toEqual({ market: 'CN', scope: 'market' });
  });

  // The 'all' default is deliberately ambiguous (it used to mean "all US"), so
  // we force the user to pick explicitly rather than silently defaulting.
  it('maps legacy "all" to an unselected state', () => {
    expect(parseLegacyUniverseDefault('all')).toEqual({ market: null, scope: null });
  });

  it('yields unselected state for null / unknown values', () => {
    expect(parseLegacyUniverseDefault(null)).toEqual({ market: null, scope: null });
    expect(parseLegacyUniverseDefault('bogus')).toEqual({ market: null, scope: null });
  });
});

describe('UNIVERSE_SCOPES_BY_MARKET', () => {
  it('exposes KOSPI and KOSDAQ scopes for Korea', () => {
    expect(UNIVERSE_SCOPES_BY_MARKET.KR).toEqual([
      { value: 'market', label: 'All Korea' },
      { value: 'exchange:KOSPI', label: 'KOSPI' },
      { value: 'exchange:KOSDAQ', label: 'KOSDAQ' },
    ]);
  });

  it('exposes SSE, SZSE, and BJSE scopes for China', () => {
    expect(UNIVERSE_SCOPES_BY_MARKET.CN).toEqual([
      { value: 'market', label: 'All China A-shares' },
      { value: 'exchange:SSE', label: 'Shanghai Stock Exchange' },
      { value: 'exchange:SZSE', label: 'Shenzhen Stock Exchange' },
      { value: 'exchange:BJSE', label: 'Beijing Stock Exchange' },
    ]);
  });
});
