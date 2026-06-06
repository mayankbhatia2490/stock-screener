import { useMemo, useState } from 'react';
import { applyScanFilterDefaults } from '../../features/scan/defaultFilters';
import { filterStaticScanRows } from '../scanClient';

export function buildFiltersFromPreset(screen, defaultFilters = {}) {
  return applyScanFilterDefaults({
    ...(screen.apply_default_filters ? defaultFilters : {}),
    ...screen.filters,
  });
}

export function usePresetScreens({
  screens,
  allRows,
  hydrationComplete,
  defaultFilters = {},
}) {
  const [activeScreenId, setActiveScreenId] = useState(null);

  const matchCounts = useMemo(() => {
    if (!hydrationComplete || !screens?.length) return {};
    return Object.fromEntries(
      screens.map((s) => [
        s.id,
        filterStaticScanRows(allRows, buildFiltersFromPreset(s, defaultFilters)).length,
      ]),
    );
  }, [allRows, defaultFilters, hydrationComplete, screens]);

  return { activeScreenId, setActiveScreenId, matchCounts };
}
