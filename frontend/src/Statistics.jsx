import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Plot } from './plotly';
import { apiFetch } from './api';
import { expandXmatchRows } from './xmatch';
const today = () => new Date().toISOString().slice(0, 10);

function rangeFor(period, date) {
  const start = period === 'month' ? `${date.slice(0, 7)}-01` : date;
  const parsed = new Date(`${start}T00:00:00Z`);
  if (period === 'month') parsed.setUTCMonth(parsed.getUTCMonth() + 1);
  else parsed.setUTCDate(parsed.getUTCDate() + 1);
  return { start, end: parsed.toISOString().slice(0, 10) };
}

export default function Statistics({ onOpenStation, onOpenEvent, theme = 'dark' }) {
  const [activeView, setActiveView] = useState('xmatch');
  const [period, setPeriod] = useState('month');
  const [date, setDate] = useState(today);
  const [ranking, setRanking] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [sourceLabel, setSourceLabel] = useState('Burst Reports');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [xmatchDate, setXmatchDate] = useState(today);
  const [xmatch, setXmatch] = useState(null);
  const [xmatchFilter, setXmatchFilter] = useState('all');
  const [xmatchLoading, setXmatchLoading] = useState(false);
  const [xmatchError, setXmatchError] = useState('');
  const openEventPointRef = useRef(null);
  const range = useMemo(() => rangeFor(period, date), [date, period]);

  const load = useCallback(async (signal) => {
    setLoading(true);
    setError('');
    setRanking([]);
    setTimeline([]);
    try {
      const params = new URLSearchParams(range);
      const [rankingResponse, timelineResponse] = await Promise.all([
        apiFetch(`/api/stats/stations?${params}`, { signal }),
        apiFetch(`/api/stats/timeline?${params}`, { signal }),
      ]);
      if (!rankingResponse.ok || !timelineResponse.ok) throw new Error('Statistics API unavailable');
      const rankingData = await rankingResponse.json();
      const timelineData = await timelineResponse.json();
      if (signal?.aborted) return;
      setRanking(rankingData.ranking ?? []);
      setTimeline(timelineData.points ?? []);
      setSourceLabel(rankingData.source_label ?? 'Burst Reports');
    } catch (cause) {
      if (!signal?.aborted) setError(cause.message);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [range]);

  const loadXmatch = useCallback(async (signal) => {
    setXmatchLoading(true);
    setXmatchError('');
    setXmatch(null);
    try {
      const response = await apiFetch(
        `/api/xmatch/timeline?date=${encodeURIComponent(xmatchDate)}`,
        { signal },
      );
      if (!response.ok) throw new Error(`Xmatch API unavailable (HTTP ${response.status})`);
      const data = await response.json();
      if (!signal?.aborted) setXmatch(data);
    } catch (cause) {
      if (!signal?.aborted) setXmatchError(cause.message);
    } finally {
      if (!signal?.aborted) setXmatchLoading(false);
    }
  }, [xmatchDate]);

  useEffect(() => {
    if (activeView !== 'summary') return undefined;
    const controller = new AbortController();
    queueMicrotask(() => load(controller.signal));
    return () => controller.abort();
  }, [activeView, load]);
  useEffect(() => {
    if (activeView !== 'xmatch') return undefined;
    const controller = new AbortController();
    queueMicrotask(() => loadXmatch(controller.signal));
    return () => controller.abort();
  }, [activeView, loadXmatch]);

  const max = Math.max(1, ...ranking.map((item) => item.count));
  const timelineMax = Math.max(1, ...timeline.map((item) => item.count));
  const xmatchRows = expandXmatchRows(xmatch?.rows, xmatchFilter);
  const availabilityTraces = xmatchRows.map((row) => {
    const x = [];
    const y = [];
    row.availability.forEach((interval) => {
      x.push(interval.start_at, interval.end_at, null);
      y.push(row.label, row.label, null);
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
  const eventPoints = xmatchRows.flatMap((row) => row.eventPoints);
  const xmatchSourceLabel = xmatch?.source_label ?? 'Burst report';
  const openEventPoint = (item) => {
    if (item.filename) {
      onOpenEvent(item.event, item.station, {
        filename: item.filename,
        focusCode: item.focusCode,
      });
    } else {
      onOpenEvent(item.event, item.station);
    }
  };
  useEffect(() => {
    openEventPointRef.current = openEventPoint;
  });
  const onXmatchClick = useCallback((click) => {
    const selected = click.points?.[0]?.customdata;
    if (selected?.event) openEventPointRef.current?.(selected);
  }, []);
  const bindXmatchClick = useCallback((_figure, graphDiv) => {
    if (!graphDiv?.on) return;
    graphDiv.removeListener?.('plotly_click', onXmatchClick);
    graphDiv.on('plotly_click', onXmatchClick);
  }, [onXmatchClick]);
  const eventTrace = {
    type: 'scatter',
    mode: 'markers',
    x: eventPoints.map((item) => item.event.started_at),
    y: eventPoints.map((item) => item.label),
    customdata: eventPoints,
    marker: { color: '#ff3b30', size: 15, symbol: 'line-ns-open', line: { color: '#ff3b30', width: 3 } },
    text: eventPoints.map((item) => `${item.station}${item.focusCode ? ` · FC ${item.focusCode}` : ''} · ${item.event.burst_type ?? 'burst'}`),
    meta: xmatchSourceLabel,
    hovertemplate: '<b>%{text}</b><br>%{x|%H:%M:%S} UTC<br>Click to open spectrogram<extra>%{meta}</extra>',
    hoverlabel: {
      align: 'left',
      bgcolor: theme === 'light' ? '#ffffff' : '#17283a',
      bordercolor: '#ff3b30',
      font: { color: theme === 'light' ? '#26384a' : '#f3f8fc', size: 12 },
    },
    name: xmatchSourceLabel,
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
          <p className="page-subtitle">Compare station coverage with the configured Burst Reports source, or review activity across the network.</p>
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
            <p>Each row is one receiver (focus code). Grey bands are archive availability; select a red {xmatch?.source_label ?? 'Burst Reports'} marker to open that exact FITS block.</p>
          </div>
          <div className="stats-controls">
            <label>Date<input type="date" value={xmatchDate} onChange={(event) => setXmatchDate(event.target.value)} /></label>
            <label>Stations<select value={xmatchFilter} onChange={(event) => setXmatchFilter(event.target.value)}><option value="all">All stations</option><option value="positive">Positive only</option></select></label>
            <button type="button" onClick={() => loadXmatch()} disabled={xmatchLoading}>{xmatchLoading ? 'Loading…' : 'Refresh'}</button>
          </div>
        </header>
        <div className="live-region" aria-live="polite">{xmatchLoading ? 'Loading Xmatch timeline' : `${xmatchRows.length} receiver rows shown in Xmatch`}</div>
        {xmatchError && <div className="page-error" role="alert">{xmatchError}<button onClick={() => loadXmatch()}>Retry</button></div>}
        {!xmatchLoading && !xmatchError && xmatchRows.length === 0 && <p className="empty-inline">No receiver rows match this filter for the selected day.</p>}
        {xmatchRows.length > 0 && (
          <>
            <Plot
              data={[...availabilityTraces, eventTrace]}
              layout={{
                autosize: true,
                height: Math.max(430, xmatchRows.length * 28 + 100),
                margin: { l: 165, r: 28, t: 18, b: 58 },
                paper_bgcolor: theme === 'light' ? '#ffffff' : '#0b1726',
                plot_bgcolor: theme === 'light' ? '#ffffff' : '#0b1726',
                font: { color: theme === 'light' ? '#26384a' : '#c8d9e8', size: 10 },
                hovermode: 'closest',
                hoverdistance: 24,
                showlegend: true,
                legend: { orientation: 'h', y: 1.04 },
                xaxis: {
                  title: 'Time (UTC)',
                  type: 'date',
                  range: [`${xmatchDate}T00:00:00Z`, `${xmatchDate}T23:59:59Z`],
                  gridcolor: theme === 'light' ? '#dce4ec' : '#24384a',
                },
                yaxis: {
                  categoryorder: 'array',
                  categoryarray: xmatchRows.map((row) => row.label).reverse(),
                  gridcolor: theme === 'light' ? '#e4eaf0' : '#1b2d3e',
                },
              }}
              config={{ responsive: true, displaylogo: false }}
              onInitialized={bindXmatchClick}
              onUpdate={bindXmatchClick}
              useResizeHandler
              style={{ width: '100%' }}
            />
            <p className="xmatch-basis">{xmatch.availability_basis}</p>
            <details className="xmatch-data">
              <summary>Receiver matches ({eventPoints.length})</summary>
              <div className="data-table-wrap">
                <table className="data-table"><thead><tr><th>UTC</th><th>Station</th><th>FC</th><th>Type</th><th>Action</th></tr></thead><tbody>
                  {eventPoints.map((item) => <tr key={`${item.station}-${item.focusCode ?? 'none'}-${item.event.id}-${item.filename ?? 'fallback'}`}><td>{item.event.started_at.slice(11, 19)}</td><td>{item.station}</td><td>{item.focusCode ?? '—'}</td><td>{item.event.burst_type ?? 'Burst'}</td><td><button className="station-link" onClick={() => openEventPoint(item)}>Open spectrogram</button></td></tr>)}
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
            <button type="button" onClick={() => load()} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
          </div>
        </div>
        <div className="live-region" aria-live="polite">{loading ? 'Loading network summary' : `${ranking.length} stations in the ranking`}</div>
        {error && <div className="page-error" role="alert">{error}<button onClick={() => load()}>Retry</button></div>}
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
          {!loading && ranking.length === 0 && !error ? <p className="empty-inline">No events available for this period.</p> : ranking.map((item, index) => (
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
