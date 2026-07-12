import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiFetch } from './api';

function rangeFor(value, period) {
  const start = period === 'month' ? `${value.slice(0, 7)}-01` : value;
  const date = new Date(`${start}T00:00:00Z`);
  if (period === 'month') date.setUTCMonth(date.getUTCMonth() + 1);
  else date.setUTCDate(date.getUTCDate() + 1);
  return { start, end: date.toISOString().slice(0, 10) };
}

export default function Statistics({ onOpenStation }) {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [period, setPeriod] = useState('day');
  const [ranking, setRanking] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [error, setError] = useState('');
  const range = useMemo(() => rangeFor(date, period), [date, period]);
  const load = useCallback(async () => {
    setError('');
    const params = new URLSearchParams(range);
    try {
      const [rankResponse, timelineResponse] = await Promise.all([
        apiFetch(`/api/stats/stations?${params}`), apiFetch(`/api/stats/timeline?${params}`),
      ]);
      if (!rankResponse.ok || !timelineResponse.ok) throw new Error(`HTTP ${rankResponse.status}/${timelineResponse.status}`);
      setRanking((await rankResponse.json()).ranking ?? []);
      setTimeline((await timelineResponse.json()).points ?? []);
    } catch (cause) { setError(`Statistics unavailable: ${cause.message}`); }
  }, [range]);
  useEffect(() => { queueMicrotask(load); }, [load]);
  const max = Math.max(1, ...ranking.map((item) => item.count));
  const timelineMax = Math.max(1, ...timeline.map((item) => item.count));
  return <main className="page-shell" id="main-content" tabIndex="-1"><header className="page-header"><div><p className="eyebrow">Network activity</p><h1>Station statistics</h1></div><div className="stats-controls"><label>Period<select value={period} onChange={(event) => setPeriod(event.target.value)}><option value="day">Day</option><option value="month">Month</option></select></label><label>Date<input type={period === 'month' ? 'month' : 'date'} value={period === 'month' ? date.slice(0, 7) : date} onChange={(event) => setDate(period === 'month' ? `${event.target.value}-01` : event.target.value)} /></label></div></header>{error && <div className="page-error" role="alert">{error}<button onClick={load}>Retry</button></div>}{period === 'month' && timeline.length > 0 && <section className="timeline-card" aria-label="Daily burst totals"><h2>Events per day</h2><div className="timeline-bars" aria-hidden="true">{timeline.map((point) => <span key={point.date} title={`${point.date}: ${point.count}`} style={{ height: `${Math.max(6, point.count / timelineMax * 100)}%` }}><i>{point.count}</i></span>)}</div><ul className="sr-only">{timeline.map((point) => <li key={point.date}>{point.date}: {point.count} events</li>)}</ul></section>}<section className="ranking-card" aria-label={`Station ranking from ${range.start} to ${range.end}`}><h2>Bursts observed</h2>{ranking.length === 0 && !error ? <p className="empty-inline">No events available for this period.</p> : ranking.map((item, index) => <button key={item.station} className="ranking-row" onClick={() => onOpenStation(item.station)}><span className="rank tabular">{index + 1}</span><span className="ranking-name">{item.station}</span><span className="ranking-bar" aria-hidden="true"><i style={{ width: `${item.count / max * 100}%` }} /></span><strong className="tabular">{item.count}</strong></button>)}</section></main>;
}
