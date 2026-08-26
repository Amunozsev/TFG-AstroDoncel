import { useEffect, useState } from 'react';
import { Plot } from './plotly';
import { apiFetch } from './api';

const DEFAULT_COLOR_SCALE = [
  [0.00, '#000000'], [0.10, '#0a0038'], [0.20, '#1a0080'],
  [0.30, '#4a0090'], [0.40, '#7a0080'], [0.50, '#aa2050'],
  [0.60, '#cc0000'], [0.70, '#e06000'], [0.80, '#f5a000'],
  [0.90, '#ffcc00'], [1.00, '#ffffb0'],
];

function utcTime(value) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'UTC',
  }).format(new Date(value));
}

export default function CombinedSpectrogram({ artifactUrl, theme = 'dark' }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!artifactUrl) return undefined;
    const controller = new AbortController();
    queueMicrotask(async () => {
      try {
        const response = await apiFetch(artifactUrl, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        setResult(await response.json());
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause.message);
      }
    });
    return () => controller.abort();
  }, [artifactUrl]);

  if (error) return <div id="combined-spectrogram-result" className="page-error" role="alert">Combined spectrogram unavailable: {error}</div>;
  if (!result?.time_axis?.length || !result?.freq_axis?.length) {
    return <div id="combined-spectrogram-result" className="result-loading" role="status">Loading combined spectrogram…</div>;
  }

  const start = result.time_axis[0];
  const end = result.time_axis.at(-1);
  const minFrequency = Math.min(...result.freq_axis);
  const maxFrequency = Math.max(...result.freq_axis);
  const plotTheme = theme === 'light'
    ? { surface: '#f7f9fc', text: '#3f5870', grid: '#d8e1ea' }
    : { surface: '#080d12', text: '#c8d9e8', grid: '#1e3448' };

  return (
    <section id="combined-spectrogram-result" className="combined-result" aria-label="Combined continuous spectrogram">
      <header>
        <div>
          <span className="section-kicker">Continuous observation</span>
          <h2>Combined spectrogram</h2>
          <p>
            {result.station} · {result.filenames.length} consecutive blocks · {utcTime(start)}–{utcTime(end)} UTC ·{' '}
            {minFrequency.toFixed(3)}–{maxFrequency.toFixed(3)} MHz
          </p>
        </div>
        <a className="btn-tool" href={artifactUrl}>View combined data (JSON)</a>
      </header>
      <Plot
        data={[{
          type: 'heatmap',
          x: result.time_axis,
          y: result.freq_axis,
          z: result.z,
          zmin: result.vmin,
          zmax: result.vmax,
          colorscale: DEFAULT_COLOR_SCALE,
          colorbar: { title: { text: 'relative<br>digits' }, thickness: 14 },
          hovertemplate: `${result.station}<br>%{x}<br>%{y:.3f} MHz<br>%{z:.2f} relative digits<extra></extra>`,
        }]}
        layout={{
          autosize: true,
          height: 430,
          margin: { l: 70, r: 110, t: 18, b: 60 },
          paper_bgcolor: plotTheme.surface,
          plot_bgcolor: plotTheme.surface,
          font: { color: plotTheme.text },
          xaxis: { title: 'Time (UTC)', type: 'date', gridcolor: plotTheme.grid },
          yaxis: { title: 'Frequency (MHz)', gridcolor: plotTheme.grid },
        }}
        config={{ responsive: true, displaylogo: false }}
        useResizeHandler
        style={{ width: '100%' }}
      />
    </section>
  );
}
