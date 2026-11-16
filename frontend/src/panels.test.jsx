// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import LightCurvePanel from './LightCurvePanel';
import Statistics from './Statistics';
import Spectrogram from './Spectrogram';
import { buildAnalysisManifest } from './analysisManifest';
import { fileForEvent } from './eventNavigation';
import { blockForEvent, expandXmatchRows } from './xmatch';

vi.mock('./plotly', () => ({
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
      'data-traces': JSON.stringify(props.data),
      disabled: !customdata,
      onClick: () => handlers.get('plotly_click')?.({ points: [{ customdata }] }),
    });
  },
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetModules();
});

// Fresh module per test: Burst Reports remembers its filters at module level.
const loadCatalog = async () => (await import('./BurstCatalog')).default;

describe('analysis panels', () => {
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

  it('loads a complete month of Burst Reports with an exclusive end date', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ events: [], warnings: [], source_label: 'deARCE (v3)' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const BurstCatalog = await loadCatalog();
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

  it('ignores an obsolete Burst Reports response after the filters change', async () => {
    const pending = [];
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => new Promise((resolve) => {
      pending.push({ url: String(url), resolve });
    })));
    const BurstCatalog = await loadCatalog();
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

  it('builds a path-free reproducibility manifest', () => {
    const manifest = buildAnalysisManifest({
      date: '2026-08-24',
      station: 'MRO',
      layers: [{
        station: 'MRO', date: '2026-08-24', filename: 'MRO_20260824_120000.fit.gz',
        unit: 'relative digits', fits_header: { 'DATE-OBS': '2026-08-24', SECRET: 'C:/private' },
      }],
      processing: { rfi_enabled: true },
      display: { colormap: 'viridis' },
      solarContext: { goes_xrs_overlay: false },
      generatedAt: '2026-08-24T12:00:00.000Z',
    });

    expect(manifest.selection.layers[0].fits_provenance).toEqual({ 'DATE-OBS': '2026-08-24' });
    expect(manifest.selection.layers[0].intensity_unit).toBe('relative digits');
    expect(JSON.stringify(manifest)).not.toContain('C:/private');
  });
});

describe('request cancellation', () => {
  it('does not revive GOES after the overlay has been turned off', async () => {
    let resolve;
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise((done) => { resolve = done; })));
    const props = {
      layers: [{ station: 'MRO', date: '2024-01-01', filename: 'MRO_20240101_120000.fit',
        time_axis: ['2024-01-01T12:00:00.000Z', '2024-01-01T12:00:01.000Z'], freq_axis: [80, 45], z: [[1, 2], [3, 4]] }],
      layerState: {}, hasLoaded: true, triggerLoad: 1, compareMode: 'panels',
      zmin: null, zmax: null,
    };
    const view = render(<Spectrogram {...props} showGoes />);
    await waitFor(() => expect(resolve).toBeTypeOf('function'));
    view.rerender(<Spectrogram {...props} showGoes={false} />);
    await act(async () => resolve({ ok: true, json: async () => ({ available: true, times: props.layers[0].time_axis, xrsb: [1, 2] }) }));
    expect(screen.getByTestId('plotly-chart').dataset.traces).not.toContain('XRS-B');
  });

  it('sends both block names when a joined observation is plotted', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ times: [], curves: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    const names = ['MRO_20240101_120000.fit', 'MRO_20240101_121500.fit'];
    render(<LightCurvePanel onCurve={vi.fn()} layer={{ station: 'MRO', date: '2024-01-01', filename: names[0], filenames: names }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Plot light curve' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(new URL(fetchMock.mock.calls[0][0]).searchParams.getAll('filenames')).toEqual(names);
  });

  it('does not deliver a light curve after its source panel unmounts', async () => {
    let resolve;
    const onCurve = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise((done) => { resolve = done; })));
    const view = render(<LightCurvePanel onCurve={onCurve} layer={{ station: 'MRO', date: '2024-01-01', filename: 'MRO_20240101_120000.fit' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Plot light curve' }));
    view.unmount();
    await act(async () => resolve({ ok: true, json: async () => ({ times: [], curves: [] }) }));
    expect(onCurve).not.toHaveBeenCalled();
  });
});
