// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import DailyOverview from './DailyOverview';
import BurstCatalog from './BurstCatalog';
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
  it('opens the clicked report station and renders catalogue longitudes', async () => {
    const onOpenEvent = vi.fn();
    const report = {
      id: 1,
      started_at: '2026-07-24T23:46:00+00:00',
      ended_at: '2026-07-24T23:48:00+00:00',
      burst_type: 'III',
      stations: ['AUSTRALIA-ASSA', 'GERMANY-DLR'],
      min_lon: -7.9,
      mid_lon: 11.1,
      max_lon: 73.7,
      source: 'dearce_v3',
      source_label: 'deARCE detection (v3)',
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ events: [report], warnings: [], source_label: report.source_label }),
    }));
    render(<BurstCatalog onOpenEvent={onOpenEvent} />);
    fireEvent.click(await screen.findByRole('button', { name: 'GERMANY-DLR' }));
    expect(onOpenEvent).toHaveBeenCalledWith(report, 'GERMANY-DLR');
    expect(screen.getByText('-7.9°')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Inspect' })).not.toBeInTheDocument();
  });

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

  it('renders every requested overview station and its receiver groups', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        start_at: '2024-01-01T02:00:00+00:00',
        end_at: '2024-01-01T05:00:00+00:00',
        baseline: 'median per station and compatible receiver group',
        intensity_unit: 'relative detector digits',
        stations: [
          {
            station: 'MRO',
            status: 'ok',
            files_skipped: 0,
            groups: [{
              id: 1,
              frequency_min_mhz: 45,
              frequency_max_mhz: 80,
              vmin: -2,
              vmax: 8,
              segments: [{ filename: 'MRO.fit', time_axis: ['2024-01-01T02:00:00Z'], freq_axis: [45], z: [[1]] }],
            }],
          },
          { station: 'BIR', status: 'no_data', files_skipped: 0, groups: [] },
        ],
      }),
    }));
    render(<DailyOverview artifactUrl="/api/tasks/example/artifact" />);
    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(2));
    expect(screen.getByText('45–80 MHz')).toBeInTheDocument();
    expect(screen.getByText('No observations in interval')).toBeInTheDocument();
  });
});
