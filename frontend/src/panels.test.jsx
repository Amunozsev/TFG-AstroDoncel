// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import DailyOverview from './DailyOverview';
import LightCurvePanel from './LightCurvePanel';

vi.mock('./plotly', () => ({ default: {} }));
vi.mock('react-plotly.js/factory', () => ({
  default: () => function PlotMock() {
    return createElement('div', { 'data-testid': 'plotly-chart' });
  },
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('analysis panels', () => {
  it('lets the user close a loaded light curve', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        times: ['2024-01-01T12:00:00Z'],
        curves: [{ frequency_mhz: 45, intensity: [1] }],
        unit: 'relative digits',
      }),
    }));
    render(<LightCurvePanel layer={{ station: 'MRO', date: '2024-01-01', filename: 'MRO_20240101_120000.fit' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Plot light curve' }));
    expect(await screen.findByRole('button', { name: 'Close light curve' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close light curve' }));
    expect(screen.queryByTestId('plotly-chart')).not.toBeInTheDocument();
  });

  it('renders all six daily overview time blocks', async () => {
    const panels = Array.from({ length: 6 }, (_, index) => ({
      start_hour: index * 4,
      end_hour: index * 4 + 4,
      segments: [],
    }));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ station: 'MRO', date: '2024-01-01', panels }),
    }));
    render(<DailyOverview artifactUrl="/api/tasks/example/artifact" />);
    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(6));
    expect(screen.getByText('20:00–24:00 UTC')).toBeInTheDocument();
  });
});
