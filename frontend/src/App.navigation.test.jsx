// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({
  API_BASE_URL: '',
  apiFetch: vi.fn(),
}));

vi.mock('./Statistics', () => ({
  default: function StatisticsMock({ onOpenEvent }) {
    return (
      <div>
        <button type="button" onClick={() => onOpenEvent({
          id: 1,
          started_at: '2026-08-26T06:32:00+00:00',
          stations: ['SPAIN-SIGUENZA'],
        }, 'SPAIN-SIGUENZA', {
          filename: 'SPAIN-SIGUENZA_20260826_063000_02.fit.gz',
          focusCode: '02',
        })}>Open Sigüenza event</button>
        <button type="button" onClick={() => onOpenEvent({
          id: 2,
          started_at: '2026-08-25T10:25:00+00:00',
          stations: ['GERMANY-DLR'],
        }, 'GERMANY-DLR', {
          filename: 'GERMANY-DLR_20260825_101500_01.fit.gz',
          focusCode: '01',
        })}>Open first DLR event</button>
        <button type="button" onClick={() => onOpenEvent({
          id: 3,
          started_at: '2026-08-25T11:06:00+00:00',
          stations: ['GERMANY-DLR'],
        }, 'GERMANY-DLR', {
          filename: 'GERMANY-DLR_20260825_110000_02.fit.gz',
          focusCode: '02',
        })}>Open second DLR event</button>
      </div>
    );
  },
}));

vi.mock('./Spectrogram', () => ({
  default: function SpectrogramMock({ layers, error }) {
    return (
      <>
        <output aria-label="Loaded FITS file">{layers[0]?.filename ?? 'none'}</output>
        <output aria-label="Layer error">{error ?? ''}</output>
      </>
    );
  },
}));
vi.mock('./StationsMap', () => ({ default: () => null }));
vi.mock('./BurstCatalog', () => ({ default: () => null }));
vi.mock('./About', () => ({ default: () => null }));
vi.mock('./DailyOverview', () => ({ default: () => null }));
vi.mock('./CombinedSpectrogram', () => ({ default: () => null }));
vi.mock('./LightCurvePanel', () => ({
  default: () => null,
  LightCurveResult: () => null,
}));

import App from './App';
import { apiFetch } from './api';

function response(data) {
  return { ok: true, status: 200, json: async () => data };
}

const filesByStation = {
  GLASGOW: [{
    filename: 'GLASGOW_20260825_123001_01.fit.gz',
    time: '12:30:01',
    label: '12:30:01',
    focus_code: '01',
  }],
  'SPAIN-SIGUENZA': [{
    filename: 'SPAIN-SIGUENZA_20260826_063000_02.fit.gz',
    time: '06:30:00',
    label: '06:30:00',
    focus_code: '02',
  }],
  'GERMANY-DLR': [
    { filename: 'GERMANY-DLR_20260825_101500_01.fit.gz', time: '10:15:00', label: '10:15:00', focus_code: '01' },
    { filename: 'GERMANY-DLR_20260825_101500_02.fit.gz', time: '10:15:00', label: '10:15:00', focus_code: '02' },
    { filename: 'GERMANY-DLR_20260825_110000_01.fit.gz', time: '11:00:00', label: '11:00:00', focus_code: '01' },
    { filename: 'GERMANY-DLR_20260825_110000_02.fit.gz', time: '11:00:00', label: '11:00:00', focus_code: '02' },
  ],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState({}, '', '/');
});

describe('catalogue navigation', () => {
  it('opens the exact FITS from a shared observation URL', async () => {
    window.history.replaceState(
      {},
      '',
      '/?station=GLASGOW&date=2026-08-25&filename=GLASGOW_20260825_123001_01.fit.gz',
    );
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      if (path === '/api/stations') {
        return response({ stations: ['GLASGOW'], source: 'ethz', details: [] });
      }
      const url = new URL(path, 'http://astrodoncel.test');
      if (url.pathname === '/api/files') {
        return response({ station: 'GLASGOW', files: filesByStation.GLASGOW });
      }
      if (url.pathname === '/api/spectrogram') {
        return response({
          station: url.searchParams.get('station'),
          date: url.searchParams.get('date'),
          filename: url.searchParams.get('filename'),
          vmin: -2,
          vmax: 8,
        });
      }
      throw new Error(`Unexpected API request: ${path}`);
    });

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText('Loaded FITS file')).toHaveTextContent(
      'GLASGOW_20260825_123001_01.fit.gz',
    ));
    expect(window.location.search).toBe(
      '?station=GLASGOW&date=2026-08-25&filename=GLASGOW_20260825_123001_01.fit.gz',
    );
  });

  it('rejects a shared URL whose FITS belongs to another station', async () => {
    window.history.replaceState(
      {},
      '',
      '/?station=GLASGOW&date=2026-08-25&filename=BIR_20260825_123001_01.fit.gz',
    );
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      if (path === '/api/stations') {
        return response({ stations: ['GLASGOW'], source: 'ethz', details: [] });
      }
      throw new Error(`Unexpected API request: ${path}`);
    });

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText('Layer error')).toHaveTextContent(
      'The FITS filename does not belong to the requested station and date.',
    ));
    expect(vi.mocked(apiFetch).mock.calls.some(([path]) => String(path).startsWith('/api/files?'))).toBe(false);
  });

  it('opens consecutive Xmatch events even when station and date repeat', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      if (path === '/api/stations') {
        return response({
          stations: ['SPAIN-SIGUENZA', 'GERMANY-DLR'],
          source: 'ethz',
          details: [],
        });
      }
      const url = new URL(path, 'http://astrodoncel.test');
      if (url.pathname === '/api/files') {
        const station = url.searchParams.get('station');
        return response({ station, files: filesByStation[station] ?? [] });
      }
      if (url.pathname === '/api/spectrogram') {
        return response({
          station: url.searchParams.get('station'),
          date: url.searchParams.get('date'),
          filename: url.searchParams.get('filename'),
          vmin: -2,
          vmax: 8,
        });
      }
      throw new Error(`Unexpected API request: ${path}`);
    });

    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: 'Statistics' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Open Sigüenza event' }));
    await waitFor(() => expect(screen.getByLabelText('Loaded FITS file')).toHaveTextContent(
      'SPAIN-SIGUENZA_20260826_063000_02.fit.gz',
    ));

    fireEvent.click(screen.getByRole('button', { name: 'Statistics' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Open first DLR event' }));
    await waitFor(() => expect(screen.getByLabelText('Loaded FITS file')).toHaveTextContent(
      'GERMANY-DLR_20260825_101500_01.fit.gz',
    ));

    fireEvent.click(screen.getByRole('button', { name: 'Statistics' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Open second DLR event' }));
    await waitFor(() => expect(screen.getByLabelText('Loaded FITS file')).toHaveTextContent(
      'GERMANY-DLR_20260825_110000_02.fit.gz',
    ));

    fireEvent.click(screen.getByRole('button', { name: 'Statistics' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Open second DLR event' }));
    await waitFor(() => expect(screen.getByLabelText('Loaded FITS file')).toHaveTextContent(
      'GERMANY-DLR_20260825_110000_02.fit.gz',
    ));

    const dlrFileRequests = vi.mocked(apiFetch).mock.calls.filter(([path]) => (
      String(path).startsWith('/api/files?')
      && String(path).includes('station=GERMANY-DLR')
      && String(path).includes('date=2026-08-25')
    ));
    expect(dlrFileRequests).toHaveLength(3);
    const repeatedSpectrogramRequests = vi.mocked(apiFetch).mock.calls.filter(([path]) => (
      String(path).startsWith('/api/spectrogram?')
      && String(path).includes('filename=GERMANY-DLR_20260825_110000_02.fit.gz')
    ));
    expect(repeatedSpectrogramRequests).toHaveLength(2);
  });

  it('reports a failed file-list request instead of showing the empty workspace', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      if (path === '/api/stations') {
        return response({
          stations: ['SPAIN-SIGUENZA', 'GERMANY-DLR'],
          source: 'ethz',
          details: [],
        });
      }
      const url = new URL(path, 'http://astrodoncel.test');
      if (url.pathname === '/api/files') throw new Error('Network unreachable');
      throw new Error(`Unexpected API request: ${path}`);
    });

    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Statistics' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Open first DLR event' }));

    await waitFor(() => expect(screen.getByLabelText('Layer error')).toHaveTextContent(
      'The FITS block list for GERMANY-DLR on 2026-08-25 could not be loaded: Network unreachable',
    ));
  });

  it('ignores an older file-list response after a newer Xmatch click', async () => {
    let resolveFirstDlrRequest;
    let dlrRequestCount = 0;
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      if (path === '/api/stations') {
        return response({
          stations: ['SPAIN-SIGUENZA', 'GERMANY-DLR'],
          source: 'ethz',
          details: [],
        });
      }
      const url = new URL(path, 'http://astrodoncel.test');
      if (url.pathname === '/api/files') {
        const station = url.searchParams.get('station');
        if (station === 'GERMANY-DLR' && ++dlrRequestCount === 1) {
          return new Promise((resolve) => { resolveFirstDlrRequest = resolve; });
        }
        return response({ station, files: filesByStation[station] ?? [] });
      }
      if (url.pathname === '/api/spectrogram') {
        return response({
          station: url.searchParams.get('station'),
          date: url.searchParams.get('date'),
          filename: url.searchParams.get('filename'),
          vmin: -2,
          vmax: 8,
        });
      }
      throw new Error(`Unexpected API request: ${path}`);
    });

    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Statistics' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Open first DLR event' }));
    await waitFor(() => expect(dlrRequestCount).toBe(1));

    fireEvent.click(screen.getByRole('button', { name: 'Statistics' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Open second DLR event' }));
    await waitFor(() => expect(screen.getByLabelText('Loaded FITS file')).toHaveTextContent(
      'GERMANY-DLR_20260825_110000_02.fit.gz',
    ));

    resolveFirstDlrRequest(response({
      station: 'GERMANY-DLR',
      files: filesByStation['GERMANY-DLR'].slice(0, 2),
    }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByLabelText('Loaded FITS file')).toHaveTextContent(
      'GERMANY-DLR_20260825_110000_02.fit.gz',
    );
  });
});
