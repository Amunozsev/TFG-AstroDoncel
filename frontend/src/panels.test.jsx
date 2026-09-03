// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import DailyOverview from './DailyOverview';
import BurstCatalog from './BurstCatalog';
import CombinedSpectrogram from './CombinedSpectrogram';
import LightCurvePanel, { LightCurveResult } from './LightCurvePanel';
import Statistics from './Statistics';
import { buildAnalysisManifest } from './analysisManifest';
import { describeBurstResult } from './burstResult';
import { fileForEvent } from './eventNavigation';
import { blockForEvent, expandXmatchRows } from './xmatch';

vi.mock('./plotly', () => ({
  default: {},
  OBSERVATORY_COLOR_SCALE: [[0, '#000000'], [1, '#ffffb0']],
  Plot: function PlotMock(props) {
    const customdata = props.data?.find((trace) => trace.customdata?.length)?.customdata?.[0];
    const handlers = new Map();
    const graphDiv = {
      on: (name, handler) => handlers.set(name, handler),
      removeListener: (name) => handlers.delete(name),
    };
    props.onInitialized?.({}, graphDiv);
    props.onUpdate?.({}, graphDiv);
    return createElement('button', {
      'aria-label': 'Mock Plotly event marker',
      'data-testid': 'plotly-chart',
      'data-x-range': props.layout?.xaxis?.range?.join('|') ?? '',
      'data-hover-template': props.data?.find((trace) => trace.customdata?.length)?.hovertemplate ?? '',
      'data-trace-name': props.data?.find((trace) => trace.customdata?.length)?.name ?? '',
      'data-hover-mode': props.layout?.hovermode ?? '',
      disabled: !customdata,
      onClick: () => (handlers.get('plotly_click') ?? props.onClick)?.({ points: [{ customdata }] }),
    });
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

  it('opens the station event represented by an Xmatch red marker', async () => {
    const onOpenEvent = vi.fn();
    const report = {
      id: 9,
      started_at: '2026-08-26T06:32:00+00:00',
      ended_at: '2026-08-26T06:35:00+00:00',
      burst_type: 'III',
      stations: ['HUMAIN'],
    };
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url) => ({
      ok: true,
      json: async () => String(url).includes('/api/xmatch/timeline')
        ? {
            source_label: 'deARCE (v3)',
            availability_basis: 'Archive blocks',
            rows: [{ station: 'HUMAIN', positive: true, availability: [], events: [report] }],
          }
        : { ranking: [], points: [] },
    })));

    render(<Statistics onOpenEvent={onOpenEvent} onOpenStation={vi.fn()} />);
    const marker = await screen.findByRole('button', { name: 'Mock Plotly event marker' });
    expect(marker).toHaveAttribute('data-hover-template', expect.stringContaining('<extra>%{meta}</extra>'));
    expect(marker).toHaveAttribute('data-trace-name', 'deARCE (v3)');
    expect(marker).toHaveAttribute('data-hover-mode', 'closest');
    fireEvent.click(marker);
    expect(onOpenEvent).toHaveBeenCalledWith(report, 'HUMAIN');
  });

  it('shows every matching focus code and opens its exact FITS block', async () => {
    const onOpenEvent = vi.fn();
    const report = {
      id: 10,
      started_at: '2026-08-25T10:25:00+00:00',
      ended_at: '2026-08-25T10:28:00+00:00',
      burst_type: 'V',
      stations: ['GERMANY-DLR'],
    };
    const receiver = (focusCode) => ({
      focus_code: focusCode,
      availability: [{
        start_at: '2026-08-25T10:15:00+00:00',
        end_at: '2026-08-25T10:30:00+00:00',
      }],
      blocks: [{
        filename: `GERMANY-DLR_20260825_101500_${focusCode}.fit.gz`,
        start_at: '2026-08-25T10:15:00+00:00',
        end_at: '2026-08-25T10:30:00+00:00',
      }],
    });
    const rows = expandXmatchRows([{
      station: 'GERMANY-DLR',
      positive: true,
      availability: [],
      receivers: ['01', '02', '03', '62', '63'].map(receiver),
      events: [report],
    }]);

    expect(rows.map((row) => row.label)).toEqual([
      'GERMANY-DLR · FC 01',
      'GERMANY-DLR · FC 02',
      'GERMANY-DLR · FC 03',
      'GERMANY-DLR · FC 62',
      'GERMANY-DLR · FC 63',
    ]);
    expect(rows.every((row) => row.eventPoints.length === 1)).toBe(true);

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        source_label: 'deARCE (v3)',
        availability_basis: 'Archive blocks by focus code',
        rows: [{
          station: 'GERMANY-DLR', positive: true, availability: [],
          receivers: ['01', '02', '03', '62', '63'].map(receiver), events: [report],
        }],
      }),
    }));
    render(<Statistics onOpenEvent={onOpenEvent} onOpenStation={vi.fn()} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Mock Plotly event marker' }));
    expect(onOpenEvent).toHaveBeenCalledWith(report, 'GERMANY-DLR', {
      filename: 'GERMANY-DLR_20260825_101500_01.fit.gz',
      focusCode: '01',
    });
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

  it('never reuses the previous station filename for a catalogue event', () => {
    const previousFiles = [{
      filename: 'SPAIN-SIGUENZA_20260826_063000_02.fit.gz',
      time: '06:30:00',
    }];
    const pendingEvent = {
      station: 'HUMAIN',
      date: '2026-08-26',
      startedAt: '2026-08-26T06:32:00+00:00',
    };

    expect(fileForEvent(
      previousFiles,
      { station: 'SPAIN-SIGUENZA', date: '2026-08-26' },
      pendingEvent,
    )).toBeNull();

    const currentFiles = [
      { filename: 'HUMAIN_20260826_061500_59.fit.gz', time: '06:15:00' },
      { filename: 'HUMAIN_20260826_063000_59.fit.gz', time: '06:30:00' },
      { filename: 'HUMAIN_20260826_064500_59.fit.gz', time: '06:45:00' },
    ];
    expect(fileForEvent(
      currentFiles,
      { station: 'HUMAIN', date: '2026-08-26' },
      pendingEvent,
    )?.filename).toBe('HUMAIN_20260826_063000_59.fit.gz');
  });

  it('uses the exact Xmatch focus-code file instead of filename ordering', () => {
    const files = ['01', '02', '03', '62', '63'].map((focusCode) => ({
      filename: `GERMANY-DLR_20260825_101500_${focusCode}.fit.gz`,
      time: '10:15:00',
      focus_code: focusCode,
    }));

    expect(fileForEvent(
      files,
      { station: 'GERMANY-DLR', date: '2026-08-25' },
      {
        station: 'GERMANY-DLR',
        date: '2026-08-25',
        startedAt: '2026-08-25T10:25:00+00:00',
        filename: 'GERMANY-DLR_20260825_101500_02.fit.gz',
        focusCode: '02',
      },
    )?.filename).toBe('GERMANY-DLR_20260825_101500_02.fit.gz');
  });

  it('does not replace a missing exact FITS with a nearby block', () => {
    const files = [{
      filename: 'GLASGOW_20260825_123000_01.fit.gz',
      time: '12:30:00',
      focus_code: '01',
    }];

    expect(fileForEvent(
      files,
      { station: 'GLASGOW', date: '2026-08-25' },
      {
        station: 'GLASGOW',
        date: '2026-08-25',
        startedAt: '2026-08-25T12:30:01Z',
        filename: 'GLASGOW_20260825_123001_01.fit.gz',
      },
    )).toBeNull();
  });

  it('prefers the new block when adjacent archive files overlap by one second', () => {
    const event = { started_at: '2026-08-25T11:15:00+00:00' };
    const blocks = [
      {
        filename: 'GERMANY-DLR_20260825_110001_63.fit.gz',
        start_at: '2026-08-25T11:00:01+00:00',
        end_at: '2026-08-25T11:15:01+00:00',
      },
      {
        filename: 'GERMANY-DLR_20260825_111500_63.fit.gz',
        start_at: '2026-08-25T11:15:00+00:00',
        end_at: '2026-08-25T11:30:00+00:00',
      },
    ];

    expect(blockForEvent(blocks, event)?.filename)
      .toBe('GERMANY-DLR_20260825_111500_63.fit.gz');
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

  it('sends an embedded light curve to the full-width result area', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        times: ['2024-01-01T12:00:00Z', '2024-01-01T12:15:00Z'],
        curves: [{ frequency_mhz: 45, intensity: [1, 2] }],
        unit: 'relative digits',
      }),
    }));
    const onCurve = vi.fn();
    const layer = { station: 'MRO', date: '2024-01-01', filename: 'MRO_20240101_120000.fit' };
    render(<LightCurvePanel layer={layer} embedded onCurve={onCurve} />);
    fireEvent.click(screen.getByRole('button', { name: 'Plot light curve' }));
    await waitFor(() => expect(onCurve).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('plotly-chart')).not.toBeInTheDocument();

    cleanup();
    const result = onCurve.mock.calls[0][0];
    render(
      <LightCurveResult
        result={result}
        timeRange={['2024-01-01T12:00:00Z', '2024-01-01T12:15:00Z']}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('Light curve aligned with the spectrogram')).toBeInTheDocument();
    expect(screen.getByTestId('plotly-chart')).toHaveAttribute(
      'data-x-range',
      '2024-01-01T12:00:00Z|2024-01-01T12:15:00Z',
    );
  });

  it('renders a combine-time artifact as a continuous spectrogram', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        station: 'MRO',
        date: '2024-01-01',
        filenames: ['MRO_20240101_120000.fit', 'MRO_20240101_121500.fit'],
        time_axis: ['2024-01-01T12:00:00Z', '2024-01-01T12:30:00Z'],
        freq_axis: [45, 80],
        z: [[1, 2], [3, 4]],
        vmin: 1,
        vmax: 4,
      }),
    }));
    render(<CombinedSpectrogram artifactUrl="/api/tasks/combine/artifact" />);

    expect(await screen.findByRole('heading', { name: 'Combined spectrogram' })).toBeInTheDocument();
    expect(screen.getByText(/2 consecutive blocks/)).toBeInTheDocument();
    expect(screen.getByText(/45\.000–80\.000 MHz/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View combined data (JSON)' })).toHaveAttribute(
      'href',
      '/api/tasks/combine/artifact',
    );
    expect(screen.getByTestId('plotly-chart')).toBeInTheDocument();
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
    expect(manifest.catalogue.label).toBe('Deployment-configured Burst Reports source');
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
