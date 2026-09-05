import { useEffect, useState } from 'react';
import { OBSERVATORY_COLOR_SCALE, Plot } from './plotly';
import { apiFetch } from './api';

const OVERVIEW_PLOT_HEIGHT = 360;
const COLOR_SCALES = [
  { value: 'default', label: 'Default' },
  { value: 'Viridis', label: 'Viridis' },
  { value: 'Cividis', label: 'Cividis' },
  { value: 'Turbo', label: 'Turbo' },
  { value: 'Greys', label: 'Greys' },
];

function utcLabel(value) {
  return value ? value.replace('T', ' ').replace('+00:00', ' UTC').replace('Z', ' UTC') : '';
}

export default function DailyOverview({ artifactUrl, theme = 'dark' }) {
  const [overview, setOverview] = useState(null);
  const [colorscale, setColorscale] = useState('default');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!artifactUrl) return undefined;
    const controller = new AbortController();
    queueMicrotask(async () => {
      if (controller.signal.aborted) return;
      setOverview(null);
      setError('');
      try {
        const response = await apiFetch(artifactUrl, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (!controller.signal.aborted) setOverview(data);
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause.message);
      }
    });
    return () => controller.abort();
  }, [artifactUrl]);

  if (error) return <div className="page-error" role="alert">Spectral overview unavailable: {error}</div>;
  if (!overview?.stations) return null;

  const stationsWithData = overview.stations.filter((item) => item.status === 'ok').length;
  const selectedColorscale = colorscale === 'default' ? OBSERVATORY_COLOR_SCALE : colorscale;
  const plotTheme = theme === 'light'
    ? { surface: '#ffffff', text: '#26384a', grid: '#dce4ec' }
    : { surface: '#0b1726', text: '#c8d9e8', grid: '#1e3448' };
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
            {COLOR_SCALES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
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
                    colorscale: selectedColorscale,
                    showscale: index === group.segments.length - 1,
                    colorbar: { title: { text: 'relative<br>digits' }, thickness: 10 },
                    hovertemplate: `${station.station}<br>%{x}<br>%{y:.3f} MHz<br>%{z:.2f} relative digits<extra></extra>`,
                  }))}
                  layout={{
                    autosize: true,
                    height: OVERVIEW_PLOT_HEIGHT,
                    margin: { l: 58, r: 70, t: 12, b: 52 },
                    paper_bgcolor: plotTheme.surface,
                    plot_bgcolor: plotTheme.surface,
                    font: { color: plotTheme.text, size: 10 },
                    xaxis: { title: 'UTC', type: 'date', gridcolor: plotTheme.grid },
                    yaxis: { title: 'Frequency (MHz)', gridcolor: plotTheme.grid },
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
