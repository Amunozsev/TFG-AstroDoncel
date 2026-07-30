// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import DailyOverview from './DailyOverview';
import BurstCatalog from './BurstCatalog';
import FullDayScanResult from './FullDayScanResult';
import LightCurvePanel from './LightCurvePanel';
import Statistics from './Statistics';

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
  it('summarizes a full-day scan and opens a candidate spectrogram', () => {
    const onOpenEvent = vi.fn();
    render(<FullDayScanResult
      task={{
        type: 'burst_detect_day',
        status: 'succeeded',
        progress: 1,
        station: 'SPAIN-SIGUENZA',
        date: '2026-07-30',
        result: {
          files_discovered: 96,
          files_processed: 94,
          files_skipped: 2,
          events_found: 2,
          events_inserted: 1,
          ml_candidates: 1,
          heuristic_candidates: 1,
          official_matches: 1,
          recommended_candidates: 1,
          candidates: [{
            id: 42,
            station: 'SPAIN-SIGUENZA',
            started_at: '2026-07-30T12:00:00Z',
            ended_at: '2026-07-30T12:01:00Z',
            source: 'ml_cnn',
            source_label: 'CNN+MIL model',
            file_score: 0.87,
            peak_score: 0.91,
            frequency_min_mhz: 45,
            frequency_max_mhz: 46,
            matched_official_burst_type: 'III',
            matched_official_event_id: 8,
            is_burst: true,
            is_recommended: true,
            filename: 'SPAIN-SIGUENZA_20260730_120000.fit.gz',
            is_new: true,
          }, {
            id: null,
            station: 'SPAIN-SIGUENZA',
            started_at: '2026-07-30T12:05:00Z',
            ended_at: '2026-07-30T12:06:00Z',
            source: 'heuristic_visual',
            source_label: 'Visual heuristic',
            file_score: 0.55,
            peak_score: 0.55,
            frequency_min_mhz: 47,
            frequency_max_mhz: 52,
            matched_official_burst_type: null,
            matched_official_event_id: null,
            is_burst: false,
            is_recommended: false,
            filename: 'SPAIN-SIGUENZA_20260730_120000.fit.gz',
            is_new: false,
          }],
        },
      }}
      onOpenEvent={onOpenEvent}
    />);

    expect(screen.getByText('94/96')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Recommended 1' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText('Visual heuristic')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open spectrogram' }));
    expect(onOpenEvent).toHaveBeenCalledWith(
      expect.objectContaining({ started_at: '2026-07-30T12:00:00Z' }),
      'SPAIN-SIGUENZA',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Experimental visual 1' }));
    expect(screen.getByText('Visual heuristic')).toBeInTheDocument();
    expect(screen.getByText(/must not be interpreted as a confirmed burst/)).toBeInTheDocument();
  });

  it('makes Xmatch the primary statistics view without losing the network summary', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url) => ({
      ok: true,
      json: async () => String(url).includes('/api/xmatch/timeline')
        ? {
            source_label: 'deARCE detection (v3)',
            availability_basis: 'Archive blocks',
            rows: [],
          }
        : String(url).includes('/api/stats/stations')
          ? { source_label: 'deARCE detection (v3)', ranking: [] }
          : { points: [] },
    })));
    render(<Statistics onOpenEvent={vi.fn()} onOpenStation={vi.fn()} />);

    expect(screen.getByRole('tab', { name: /Xmatch timeline/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { name: 'Xmatch timeline' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Bursts observed' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /Network summary/ }));
    expect(await screen.findByRole('heading', { name: 'Bursts observed' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Network summary/ })).toHaveAttribute('aria-selected', 'true');
  });

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
