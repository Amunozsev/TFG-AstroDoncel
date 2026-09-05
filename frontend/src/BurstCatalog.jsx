import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from './api';
import { observationDateRange } from './observationUrl';

function csvCell(value) {
  const text = value == null ? '' : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

export default function BurstCatalog({ onOpenEvent }) {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [period, setPeriod] = useState('day');
  const [type, setType] = useState('');
  const [station, setStation] = useState('');
  const [events, setEvents] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [availableTypes, setAvailableTypes] = useState([]);
  const [sourceLabel, setSourceLabel] = useState('Burst Reports');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = () => setRefreshKey((value) => value + 1);

  const load = useCallback(async (signal) => {
    if (signal.aborted) return;
    const range = observationDateRange(date, period);
    if (!range) {
      setLoading(false);
      setEvents([]);
      setError('Select a valid date.');
      return;
    }
    setLoading(true);
    setError('');
    const query = new URLSearchParams(range);
    if (type) query.set('type', type);
    if (station) query.set('station', station);
    try {
      const response = await apiFetch(`/api/bursts?${query}`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (signal?.aborted) return;
      setEvents(data.events ?? []);
      setWarnings(data.warnings ?? []);
      setAvailableTypes(data.available_types ?? []);
      setSourceLabel(data.source_label ?? 'Burst Reports');
    } catch (cause) {
      if (!signal?.aborted) setError(`Could not load the burst catalogue: ${cause.message}`);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [date, period, station, type]);

  useEffect(() => {
    const controller = new AbortController();
    const delay = station ? 250 : 0;
    const timer = window.setTimeout(() => load(controller.signal), delay);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [load, station, refreshKey]);

  const formatLongitude = (value) => Number.isFinite(value) ? `${value.toFixed(1)}°` : '—';

  function exportCsv() {
    const header = ['Date', 'Start UTC', 'End UTC', 'Key', 'Type', 'Intensity', 'Remarks', 'Stations', 'Min lon', 'Mid lon', 'Max lon', 'Source'];
    const rows = events.map((event) => {
      const started = new Date(event.started_at);
      const ended = new Date(event.ended_at);
      return [
        started.toISOString().slice(0, 10), started.toISOString(), ended.toISOString(),
        event.metadata?.key, event.burst_type ?? '—', event.intensity,
        event.metadata?.remarks, event.stations.join('; '),
        event.min_lon, event.mid_lon, event.max_lon, event.source_label ?? event.source,
      ];
    });
    const csv = [header, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `burst-reports-${period === 'month' ? date.slice(0, 7) : date}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="page-shell" id="main-content" tabIndex="-1">
      <header className="page-header">
        <div>
          <p className="eyebrow">Scientific catalogue</p>
          <h1>Burst Reports</h1>
          <p className="page-subtitle">
            Catalogue: {sourceLabel}. Select any station to open the FITS block containing that event.
          </p>
        </div>
      </header>
      <section className="filter-bar" aria-label="Burst filters">
        <label>Period<select value={period} onChange={(event) => setPeriod(event.target.value)}><option value="day">Day</option><option value="month">Full month</option></select></label>
        <label>{period === 'month' ? 'Month' : 'Date'}<input type={period === 'month' ? 'month' : 'date'} value={period === 'month' ? date.slice(0, 7) : date} onChange={(event) => setDate(period === 'month' && event.target.value ? `${event.target.value}-01` : event.target.value)} /></label>
        <label>Type<select value={type} onChange={(event) => setType(event.target.value)}><option value="">All types</option>{availableTypes.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Station<input value={station} onChange={(event) => setStation(event.target.value)} placeholder="Search stations…" /></label>
        <button className="btn-primary" onClick={refresh} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
        <button type="button" onClick={exportCsv} disabled={loading || events.length === 0}>Export CSV</button>
      </section>
      <div className="live-region" aria-live="polite">{loading ? 'Loading burst reports' : `${events.length} events found for the selected ${period}`}</div>
      {error && <div className="page-error" role="alert">{error}<button onClick={refresh}>Retry</button></div>}
      {warnings.length > 0 && <p className="page-warning">Some source months were unavailable. Cached results are shown.</p>}
      {!loading && !error && events.length === 0 ? (
        <div className="empty-card"><h2>No events found</h2><p>Try another date or remove filters.</p></div>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table burst-report-table">
            <caption className="sr-only">Solar radio burst catalogue</caption>
            <thead><tr><th>Date</th><th>UTC interval</th><th>Key</th><th>Type</th><th>Intensity</th><th>Remarks</th><th>Stations</th><th>Min. lon</th><th>Mid. lon</th><th>Max. lon</th><th>Source</th></tr></thead>
            <tbody>{events.map((event) => {
              const started = new Date(event.started_at);
              const ended = new Date(event.ended_at);
              return (
                <tr key={event.id}>
                  <td>{started.toISOString().slice(0, 10)}</td>
                  <td className="tabular">{started.toISOString().slice(11, 16)}–{ended.toISOString().slice(11, 16)}</td>
                  <td>{event.metadata?.key ?? '—'}</td>
                  <td><span className="type-badge">{event.burst_type ?? '—'}</span></td>
                  <td className="tabular">{event.intensity ?? '—'}</td>
                  <td>{event.metadata?.remarks ?? '—'}</td>
                  <td>
                    <span className="station-links">
                      {event.stations.map((item) => (
                        <button
                          key={item}
                          className="station-link"
                          onClick={() => onOpenEvent(event, item)}
                          title={`Open ${item} at ${started.toISOString().slice(11, 16)} UTC`}
                        >
                          {item}
                        </button>
                      ))}
                    </span>
                  </td>
                  <td className="tabular longitude-cell">{formatLongitude(event.min_lon)}</td>
                  <td className="tabular longitude-cell">{formatLongitude(event.mid_lon)}</td>
                  <td className="tabular longitude-cell">{formatLongitude(event.max_lon)}</td>
                  <td><span className="source-badge">{event.source_label ?? event.source}</span></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      )}
    </main>
  );
}
