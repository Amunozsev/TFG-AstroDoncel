import { useEffect, useState } from 'react';
import Plotly from './plotly';
import _factory from 'react-plotly.js/factory';
import { apiFetch } from './api';

const Plot = (_factory.default ?? _factory)(Plotly);
const COLOR_SCALES = ['Viridis', 'Cividis', 'Turbo', 'Greys'];

function utcLabel(value) {
  return value ? value.replace('T', ' ').replace('+00:00', ' UTC').replace('Z', ' UTC') : '';
}

export default function DailyOverview({ artifactUrl }) {
  const [overview, setOverview] = useState(null);
  const [colorscale, setColorscale] = useState('Viridis');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!artifactUrl) return undefined;
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

  if (error) return <div className="page-error" role="alert">Spectral overview unavailable: {error}</div>;
  if (!overview?.stations) return null;

  const stationsWithData = overview.stations.filter((item) => item.status === 'ok').length;
  return (
    <section className="daily-overview" aria-label="Spectral overview for the requested UTC interval">
      <header>
        <div>
          <h2>Spectral overview</h2>
          <span>{utcLabel(overview.start_at)} – {utcLabel(overview.end_at)}</span>
          <p>{stationsWithData}/{overview.stations.length} stations with observations · {overview.baseline} · {overview.intensity_unit}</p>
        </div>
        <label className="overview-colormap">
          Colour scale
          <select value={colorscale} onChange={(event) => setColorscale(event.target.value)}>
            {COLOR_SCALES.map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
      </header>
      <div className="overview-stations">
        {overview.stations.map((station) => (
          <article className={`overview-station-card ${station.status}`} key={station.station}>
            <h3>
              <span>{station.station}</span>
              {station.status === 'ok' ? <small>{station.groups.length} receiver group{station.groups.length === 1 ? '' : 's'}</small> : <small>No observations in interval</small>}
            </h3>
            {station.files_skipped > 0 && <p className="overview-warning">{station.files_skipped} unreadable file{station.files_skipped === 1 ? '' : 's'} skipped.</p>}
            {station.groups.map((group) => (
              <div className="overview-receiver" key={`${station.station}-${group.id}`}>
                <p>{group.frequency_min_mhz}–{group.frequency_max_mhz} MHz</p>
                <Plot
                  data={group.segments.map((segment, index) => ({
                    type: 'heatmap',
                    x: segment.time_axis,
                    y: segment.freq_axis,
                    z: segment.z,
                    zmin: group.vmin,
                    zmax: group.vmax,
                    colorscale,
                    showscale: index === group.segments.length - 1,
                    colorbar: { title: { text: 'relative<br>digits' }, thickness: 10 },
                    hovertemplate: `${station.station}<br>%{x}<br>%{y:.3f} MHz<br>%{z:.2f} relative digits<extra></extra>`,
                  }))}
                  layout={{
                    autosize: true,
                    height: 270,
                    margin: { l: 58, r: 70, t: 12, b: 52 },
                    paper_bgcolor: '#0b1726',
                    plot_bgcolor: '#0b1726',
                    font: { color: '#c8d9e8', size: 10 },
                    xaxis: { title: 'UTC', type: 'date', gridcolor: '#1e3448' },
                    yaxis: { title: 'Frequency (MHz)', gridcolor: '#1e3448' },
                  }}
                  config={{ responsive: true, displaylogo: false }}
                  useResizeHandler
                  style={{ width: '100%' }}
                />
              </div>
            ))}
          </article>
        ))}
      </div>
    </section>
  );
}
