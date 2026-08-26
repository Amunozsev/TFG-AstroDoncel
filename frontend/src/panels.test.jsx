// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import DailyOverview from './DailyOverview';
import BurstCatalog from './BurstCatalog';
import LightCurvePanel from './LightCurvePanel';
import Statistics from './Statistics';
import { buildAnalysisManifest } from './analysisManifest';
import { describeBurstResult } from './burstResult';

vi.mock('./plotly', () => ({
  default: {},
  Plot: function PlotMock() {
    return createElement('div', { 'data-testid': 'plotly-chart' });
  },
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('analysis panels', () => {
  it('makes Xmatch the primary statistics view without losing the network summary', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url) => ({
      ok: true,
      json: async () => String(url).includes('/api/xmatch/timeline')
        ? {
            source_label: 'deARCE (v3)',
            availability_basis: 'Archive blocks',
            rows: [],
          }
        : String(url).includes('/api/stats/stations')
          ? { source_label: 'deARCE (v3)', ranking: [] }
          : { points: [] },
    })));
    render(<Statistics onOpenEvent={vi.fn()} onOpenStation={vi.fn()} />);

    expect(screen.getByRole('tab', { name: /Xmatch timeline/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { name: 'Xmatch timeline' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Bursts observed' })).not.toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(vi.mocked(fetch).mock.calls.every(([url]) => !String(url).includes('/api/stats/'))).toBe(true);

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
      source_label: 'deARCE (v3)',
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

  it('loads a complete month of Burst Reports with an exclusive end date', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ events: [], warnings: [], source_label: 'deARCE (v3)' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<BurstCatalog onOpenEvent={vi.fn()} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText('Period'), { target: { value: 'month' } });
    fireEvent.change(screen.getByLabelText('Month'), { target: { value: '2026-07' } });

    await waitFor(() => {
      const url = String(fetchMock.mock.calls.at(-1)[0]);
      expect(url).toContain('start=2026-07-01');
      expect(url).toContain('end=2026-08-01');
    });
  });

  it('searches Burst Reports with a partial station name', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ events: [], warnings: [], source_label: 'deARCE (v3)' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<BurstCatalog onOpenEvent={vi.fn()} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText('Station'), { target: { value: 'glas' } });

    await waitFor(() => {
      const url = String(fetchMock.mock.calls.at(-1)[0]);
      expect(url).toContain('station=glas');
    });
    expect(screen.getByLabelText('Station')).toHaveValue('glas');
  });

  it('ignores an obsolete Burst Reports response after the filters change', async () => {
    const pending = [];
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => new Promise((resolve) => {
      pending.push({ url: String(url), resolve });
    })));
    render(<BurstCatalog onOpenEvent={vi.fn()} />);
    await waitFor(() => expect(pending).toHaveLength(1));

    fireEvent.change(screen.getByLabelText('Station'), { target: { value: 'glas' } });
    await waitFor(() => expect(pending).toHaveLength(2));
    pending[1].resolve({
      ok: true,
      json: async () => ({
        events: [{
          id: 2, started_at: '2026-08-26T06:00:00Z', ended_at: '2026-08-26T06:01:00Z',
          stations: ['GLASGOW'], burst_type: 'III', source_label: 'deARCE (v3)',
        }],
        warnings: [], source_label: 'deARCE (v3)',
      }),
    });
    expect(await screen.findByRole('button', { name: 'GLASGOW' })).toBeInTheDocument();

    pending[0].resolve({
      ok: true,
      json: async () => ({
        events: [{
          id: 1, started_at: '2026-08-26T05:00:00Z', ended_at: '2026-08-26T05:01:00Z',
          stations: ['MRO'], burst_type: 'III', source_label: 'deARCE (v3)',
        }],
        warnings: [], source_label: 'deARCE (v3)',
      }),
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole('button', { name: 'MRO' })).not.toBeInTheDocument();
  });

  it('reports a positive file even when event localization is empty', () => {
    const summary = describeBurstResult({
      available: true, is_burst: true, is_candidate: false,
      file_score: 0.81, threshold: 0.6, events: [],
    });
    expect(summary.label).toBe('Burst detected');
    expect(summary.detail).toMatch(/no reliable time-frequency interval/i);
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
    const fetchMock = vi.mocked(fetch);
    render(<LightCurvePanel layer={{ station: 'MRO', date: '2024-01-01', filename: 'MRO_20240101_120000.fit' }} />);
    fireEvent.change(screen.getByLabelText('Frequencies (MHz)'), { target: { value: '45, 55' } });
    fireEvent.click(screen.getByRole('button', { name: 'Plot light curve' }));
    expect(await screen.findByRole('button', { name: 'Close light curve' })).toBeInTheDocument();
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain('freq_mhz=45');
    expect(url).toContain('freq_mhz=55');
    fireEvent.click(screen.getByRole('button', { name: 'Close light curve' }));
    expect(screen.queryByTestId('plotly-chart')).not.toBeInTheDocument();
  });

  it('builds a path-free reproducibility manifest', () => {
    const manifest = buildAnalysisManifest({
      date: '2026-08-24',
      station: 'MRO',
      layers: [{
        station: 'MRO', date: '2026-08-24', filename: 'MRO_20260824_120000.fit.gz',
        intensity_unit: 'relative digits', fits_header: { 'DATE-OBS': '2026-08-24', SECRET: 'C:/private' },
      }],
      processing: { rfi_enabled: true },
      display: { colormap: 'viridis' },
      solarContext: { goes_xrs_overlay: false },
      generatedAt: '2026-08-24T12:00:00.000Z',
    });

    expect(manifest.schema).toBe('astrodoncel.analysis-manifest.v1');
    expect(manifest.catalogue.label).toBe('deARCE (v3)');
    expect(manifest.selection.layers[0].fits_provenance).toEqual({ 'DATE-OBS': '2026-08-24' });
    expect(JSON.stringify(manifest)).not.toContain('C:/private');
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
    expect(screen.getByLabelText('Colour scale')).toHaveValue('default');
    expect(screen.getByRole('option', { name: 'Default' })).toBeInTheDocument();
    expect(screen.getByText('45–80 MHz')).toBeInTheDocument();
    expect(screen.getByText('No observations in interval')).toBeInTheDocument();
  });
});
