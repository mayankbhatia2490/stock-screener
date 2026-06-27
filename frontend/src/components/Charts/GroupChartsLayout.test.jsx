import { ThemeProvider, createTheme } from '@mui/material/styles';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import GroupChartsLayout, { GroupChartCell } from './GroupChartsLayout';

describe('GroupChartsLayout', () => {
  it('provides the shared two-column desktop chart grid contract', () => {
    render(
      <ThemeProvider theme={createTheme()}>
        <GroupChartsLayout data-testid="shared-group-charts-layout" gap={2}>
          <GroupChartCell data-testid="shared-group-chart-cell">AAA</GroupChartCell>
          <GroupChartCell>BBB</GroupChartCell>
        </GroupChartsLayout>
      </ThemeProvider>,
    );

    const layout = screen.getByTestId('shared-group-charts-layout');
    expect(layout).toHaveStyle({
      display: 'grid',
      gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
    });
    expect(screen.getByTestId('shared-group-chart-cell')).toHaveStyle({ minWidth: '0' });
  });
});
