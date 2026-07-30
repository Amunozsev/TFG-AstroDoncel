import { useCallback, useEffect, useMemo, useState } from 'react';
import Plotly from './plotly';
import _factory from 'react-plotly.js/factory';
import { apiFetch } from './api';

const Plot = (_factory.default ?? _factory)(Plotly);
const today = () => new Date().toISOString().slice(0, 10);

function rangeFor(period, date) {
  const start = period === 'month' ? `${date.slice(0, 7)}-01` : date;
  const parsed = new Date(`${start}T00:00:00Z`);
  if (period === 'month') parsed.setUTCMonth(parsed.getUTCMonth() + 1);
  else parsed.setUTCDate(parsed.getUTCDate() + 1);
  return { start, end: parsed.toISOString().slice(0, 10) };
}

export default function Statistics({ onOpenStation, onOpenEvent }) {
  const [activeView, setActiveView] = useState('xmatch');
  const [period, setPeriod] = useState('month');
  const [date, setDate] = useState(today);
  const [ranking, setRanking] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [sourceLabel, setSourceLabel] = useState('deARCE detection (v3)');
  const [error, setError] = useState('');
  const [xmatchDate, setXmatchDate] = useState(today);
  const [xmatch, setXmatch] = useState(null);
  const [xmatchFilter, setXmatchFilter] = useState('all');
  const [xmatchError, setXmatchError] = useState('');
  const range = useMemo(() => rangeFor(period, date), [date, period]);

  const load = useCallback(async () => {
    setError('');
    try {
      const params = new URLSearchParams(range);
      const [rankingResponse, timelineResponse] = await Promise.all([
        apiFetch(`/api/stats/stations?${params}`),
        apiFetch(`/api/stats/timeline?${params}`),
      ]);
      if (!rankingResponse.ok || !timelineResponse.ok) throw new Error('Statistics API unavailable');
      const rankingData = await rankingResponse.json();
      const timelineData = await timelineResponse.json();
      setRanking(rankingData.ranking ?? []);
      setTimeline(timelineData.points ?? []);
      setSourceLabel(rankingData.source_label ?? 'deARCE detection (v3)');
    } catch (cause) {
      setError(cause.message);
    }
  }, [range]);

  const loadXmatch = useCallback(async () => {
    setXmatchError('');
    try {
      const response = await apiFetch(`/api/xmatch/timeline?date=${encodeURIComponent(xmatchDate)}`);
      if (!response.ok) throw new Error(`Xmatch API unavailable (HTTP ${response.status})`);
      setXmatch(await response.json());
    } catch (cause) {
      setXmatchError(cause.message);
    }
  }, [xmatchDate]);

  useEffect(() => { queueMicrotask(load); }, [load]);
  useEffect(() => { queueMicrotask(loadXmatch); }, [loadXmatch]);

  const max = Math.max(1, ...ranking.map((item) => item.count));
  const timelineMax = Math.max(1, ...timeline.map((item) => item.count));
  const xmatchRows = (xmatch?.rows ?? []).filter((row) => xmatchFilter === 'all' || row.positive);
  const availabilityTraces = xmatchRows.map((row) => {
    const x = [];
    const y = [];
    row.availability.forEach((interval) => {
      x.push(interval.start_at, interval.end_at, null);
      y.push(row.station, row.station, null);
    });
    return {
      type: 'scatter',
      mode: 'lines',
      x,
      y,
      line: { color: '#6b7280', width: 12 },
      hoverinfo: 'skip',
      showlegend: false,
    };
  });
  const eventPoints = xmatchRows.flatMap((row) => row.events.map((event) => ({
    station: row.station,
    event,
  })));
  const eventTrace = {
    type: 'scatter',
    mode: 'markers',
    x: eventPoints.map((item) => item.event.started_at),
    y: eventPoints.map((item) => item.station),
    customdata: eventPoints,
    marker: { color: '#ff3b30', size: 15, symbol: 'line-ns-open', line: { color: '#ff3b30', width: 3 } },
    text: eventPoints.map((item) => `${item.station} · ${item.event.burst_type ?? 'burst'}`),
    hovertemplate: '%{text}<br>%{x|%H:%M:%S} UTC<br>Click to open spectrogram<extra></extra>',
    name: 'deARCE burst',
  };

  const handleViewKeyDown = (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const nextView = event.key === 'Home' || event.key === 'ArrowLeft' ? 'xmatch' : 'summary';
    setActiveView(nextView);
    document.getElementById(`statistics-tab-${nextView}`)?.focus();
  };

  return (
    <main className="page-shell statistics-page" id="main-content" tabIndex="-1">
      <header className="page-header">
        <div>
          <p className="eyebrow">Network intelligence</p>
          <h1>Statistics &amp; Xmatch</h1>
          <p className="page-subtitle">Compare station coverage with deARCE bursts, or review activity across the network.</p>
        </div>
      </header>

      <div className="statistics-view-switcher" role="tablist" aria-label="Statistics views" onKeyDown={handleViewKeyDown}>
        <button
          id="statistics-tab-xmatch"
          type="button"
          role="tab"
          aria-selected={activeView === 'xmatch'}
          aria-controls="statistics-panel-xmatch"
          tabIndex={activeView === 'xmatch' ? 0 : -1}
          onClick={() => setActiveView('xmatch')}
        >
          <strong>Xmatch timeline</strong>
          <span>Availability + burst markers</span>
        </button>
        <button
          id="statistics-tab-summary"
          type="button"
          role="tab"
          aria-selected={activeView === 'summary'}
          aria-controls="statistics-panel-summary"
          tabIndex={activeView === 'summary' ? 0 : -1}
          onClick={() => setActiveView('summary')}
        >
          <strong>Network summary</strong>
          <span>Daily totals + station ranking</span>
        </button>
      </div>

      {activeView === 'xmatch' && <section
        className="xmatch-card"
        id="statistics-panel-xmatch"
        role="tabpanel"
        aria-labelledby="statistics-tab-xmatch"
      >
        <header>
          <div>
            <p className="eyebrow">Cross-station context</p>
            <h2 id="xmatch-title">Xmatch timeline</h2>
            <p>Grey bands are archive availability. Red markers are {xmatch?.source_label ?? 'deARCE detections'}; select one to open that station at the event time.</p>
          </div>
          <div className="stats-controls">
            <label>Date<input type="date" value={xmatchDate} onChange={(event) => setXmatchDate(event.target.value)} /></label>
            <label>Stations<select value={xmatchFilter} onChange={(event) => setXmatchFilter(event.target.value)}><option value="all">All stations</option><option value="positive">Positive only</option></select></label>
          </div>
        </header>
        {xmatchError && <div className="page-error" role="alert">{xmatchError}<button onClick={loadXmatch}>Retry</button></div>}
        {!xmatchError && xmatchRows.length === 0 && <p className="empty-inline">No stations match this filter for the selected day.</p>}
        {xmatchRows.length > 0 && (
          <>
            <Plot
              data={[...availabilityTraces, eventTrace]}
              layout={{
                autosize: true,
                height: Math.max(430, xmatchRows.length * 28 + 100),
                margin: { l: 165, r: 28, t: 18, b: 58 },
                paper_bgcolor: '#0b1726',
                plot_bgcolor: '#0b1726',
                font: { color: '#c8d9e8', size: 10 },
                showlegend: true,
                legend: { orientation: 'h', y: 1.04 },
                xaxis: {
                  title: 'Time (UTC)',
                  type: 'date',
                  range: [`${xmatchDate}T00:00:00Z`, `${xmatchDate}T23:59:59Z`],
                  gridcolor: '#24384a',
                },
                yaxis: {
                  categoryorder: 'array',
                  categoryarray: xmatchRows.map((row) => row.station).reverse(),
                  gridcolor: '#1b2d3e',
                },
              }}
              config={{ responsive: true, displaylogo: false }}
              onClick={(click) => {
                const selected = click.points?.[0]?.customdata;
                if (selected?.event) onOpenEvent(selected.event, selected.station);
              }}
              useResizeHandler
              style={{ width: '100%' }}
            />
            <p className="xmatch-basis">{xmatch.availability_basis}</p>
            <details className="xmatch-data">
              <summary>Event list ({eventPoints.length})</summary>
              <div className="data-table-wrap">
                <table className="data-table"><thead><tr><th>UTC</th><th>Station</th><th>Type</th><th>Action</th></tr></thead><tbody>
                  {eventPoints.map((item) => <tr key={`${item.station}-${item.event.id}`}><td>{item.event.started_at.slice(11, 19)}</td><td>{item.station}</td><td>{item.event.burst_type ?? 'Burst'}</td><td><button className="station-link" onClick={() => onOpenEvent(item.event, item.station)}>Open spectrogram</button></td></tr>)}
                </tbody></table>
              </div>
            </details>
          </>
        )}
      </section>}

      {activeView === 'summary' && <section
        className="statistics-summary"
        id="statistics-panel-summary"
        role="tabpanel"
        aria-labelledby="statistics-tab-summary"
      >
        <div className="statistics-summary-toolbar">
          <div>
            <p className="eyebrow">Catalogue activity</p>
            <h2>Network summary</h2>
            <p>Catalogue: {sourceLabel}</p>
          </div>
          <div className="stats-controls">
            <label>Period<select value={period} onChange={(event) => setPeriod(event.target.value)}><option value="day">Day</option><option value="month">Month</option></select></label>
            <label>Date<input type={period === 'month' ? 'month' : 'date'} value={period === 'month' ? date.slice(0, 7) : date} onChange={(event) => setDate(period === 'month' ? `${event.target.value}-01` : event.target.value)} /></label>
          </div>
        </div>
        {error && <div className="page-error" role="alert">{error}<button onClick={load}>Retry</button></div>}
        {period === 'month' && timeline.length > 0 && (
          <section className="timeline-card" aria-label="Daily burst totals">
            <h2>Events per day</h2>
            <div className="timeline-bars">
              {timeline.map((point) => (
                <span className="timeline-bar-item" key={point.date} title={`${point.date}: ${point.count}`}>
                  <i style={{ height: point.count ? `${Math.max(6, point.count / timelineMax * 100)}%` : 0 }}><b>{point.count}</b></i>
                  <small>{point.date.slice(-2)}</small>
                </span>
              ))}
            </div>
          </section>
        )}
        <section className="ranking-card" aria-label={`Station ranking from ${range.start} to ${range.end}`}>
          <h2>Bursts observed</h2>
          {ranking.length === 0 && !error ? <p className="empty-inline">No events available for this period.</p> : ranking.map((item, index) => (
            <button key={item.station} className="ranking-row" onClick={() => onOpenStation(item.station)}>
              <span className="rank tabular">{index + 1}</span>
              <span className="ranking-name">{item.station}</span>
              <span className="ranking-bar" aria-hidden="true"><i style={{ width: `${item.count / max * 100}%` }} /></span>
              <strong className="tabular">{item.count}</strong>
            </button>
          ))}
        </section>
      </section>}
    </main>
  );
}
