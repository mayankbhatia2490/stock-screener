import { Box, useMediaQuery, useTheme } from '@mui/material';

const TWO_COLUMN_TEMPLATE = 'repeat(2, minmax(0, 1fr))';

const mergeSx = (base, sx) => (
  Array.isArray(sx)
    ? [base, ...sx]
    : [base, sx].filter(Boolean)
);

function GroupChartsLayout({ children, gap = 1, sx, ...props }) {
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up('md'), { defaultMatches: true });

  return (
    <Box
      {...props}
      sx={mergeSx(
        {
          display: 'grid',
          gridTemplateColumns: isDesktop ? TWO_COLUMN_TEMPLATE : '1fr',
          gap,
        },
        sx,
      )}
    >
      {children}
    </Box>
  );
}

export function GroupChartCell({ sx, ...props }) {
  return <Box {...props} sx={mergeSx({ minWidth: 0 }, sx)} />;
}

export default GroupChartsLayout;
