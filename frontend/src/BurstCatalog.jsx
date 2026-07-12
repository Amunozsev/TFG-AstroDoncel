import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from './api';

export default function BurstCatalog({ onOpenEvent }) {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [type, setType] = useState('');
  const [station, setStation] = useState('');
  const [events, setEvents] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    const query = new URLSearchParams({ start: date });
    if (type) query.set('type', type);
    if (station) query.set('station', station);
    try {
      const response = await apiFetch(`/api/bursts?${query}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setEvents(data.events ?? []); setWarnings(data.warnings ?? []);
    } catch (cause) {
      setError(`Could not load the burst catalogue: ${cause.message}`);
    } finally { setLoading(false); }
  }, [date, station, type]);

  useEffect(() => { queueMicrotask(load); }, [load]);

  return (
    <main className="page-shell" id="main-content" tabIndex="-1">
      <header className="page-header"><div><p className="eyebrow">Scientific catalogue</p><h1>Burst Reports</h1></div></header>
      <section className="filter-bar" aria-label="Burst filters">
        <label>Date<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
        <label>Type<select value={type} onChange={(event) => setType(event.target.value)}><option value="">All types</option>{['II','III','IIIG','V','VI','U','J','CTM','RBR'].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Station<input value={station} onChange={(event) => setStation(event.target.value.toUpperCase())} placeholder="e.g. SPAIN-SIGUENZA" /></label>
        <button className="btn-primary" onClick={load} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
      </section>
      <div className="live-region" aria-live="polite">{loading ? 'Loading burst reports' : `${events.length} events found`}</div>
      {error && <div className="page-error" role="alert">{error}<button onClick={load}>Retry</button></div>}
      {warnings.length > 0 && <p className="page-warning">Some source months were unavailable. Cached results are shown.</p>}
      {!loading && !error && events.length === 0 ? <div className="empty-card"><h2>No events found</h2><p>Try another date or remove filters.</p></div> : (
        <div className="data-table-wrap"><table className="data-table"><caption className="sr-only">Solar radio burst catalogue</caption><thead><tr><th>Date</th><th>UTC interval</th><th>Type</th><th>Stations</th><th>Source</th><th><span className="sr-only">Open</span></th></tr></thead><tbody>{events.map((event) => {
          const started = new Date(event.started_at); const ended = new Date(event.ended_at);
          return <tr key={event.id}><td>{started.toISOString().slice(0,10)}</td><td className="tabular">{started.toISOString().slice(11,16)}–{ended.toISOString().slice(11,16)}</td><td><span className="type-badge">{event.burst_type ?? 'Candidate'}</span></td><td>{event.stations.join(', ')}</td><td>{event.source}</td><td><button className="btn-table" onClick={() => onOpenEvent(event)}>Inspect</button></td></tr>;
        })}</tbody></table></div>
      )}
    </main>
  );
}
