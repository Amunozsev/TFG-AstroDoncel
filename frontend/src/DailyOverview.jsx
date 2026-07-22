import { useEffect, useState } from 'react';
import Plotly from './plotly';
import _factory from 'react-plotly.js/factory';
import { apiFetch } from './api';

const Plot = (_factory.default ?? _factory)(Plotly);

export default function DailyOverview({ artifactUrl }) {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!artifactUrl) return;
    const controller = new AbortController();
    queueMicrotask(async () => {
      try {
        const response = await apiFetch(artifactUrl, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        setOverview(await response.json());
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause.message);
      }
    });
    return () => controller.abort();
  }, [artifactUrl]);
  if (error) return <div className="page-error" role="alert">Daily overview unavailable: {error}</div>;
  if (!overview?.panels) return null;
  return <section className="daily-overview" aria-label={`Daily spectral overview for ${overview.station}`}><header><h2>Daily spectral overview</h2><span>{overview.station} · {overview.date} · daily median baseline</span></header><div className="overview-grid">{overview.panels.map((panel) => <article key={panel.start_hour}><h3>{String(panel.start_hour).padStart(2, '0')}:00–{String(panel.end_hour).padStart(2, '0')}:00 UTC</h3>{panel.segments.length === 0 ? <p>No observations</p> : <Plot data={panel.segments.map((segment) => ({ type: 'heatmap', x: segment.time_axis, y: segment.freq_axis, z: segment.z, colorscale: 'Hot', showscale: false, hovertemplate: '%{x}<br>%{y} MHz<br>%{z:.2f}<extra></extra>' }))} layout={{ autosize: true, height: 220, margin: { l: 55, r: 10, t: 10, b: 40 }, paper_bgcolor: '#0b1726', plot_bgcolor: '#0b1726', font: { color: '#c8d9e8', size: 10 }, xaxis: { title: 'UTC' }, yaxis: { title: 'MHz' } }} config={{ responsive: true, displaylogo: false }} useResizeHandler style={{ width: '100%' }} />}</article>)}</div></section>;
}
