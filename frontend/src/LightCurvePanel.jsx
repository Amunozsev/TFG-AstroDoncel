import { useState } from 'react';
import Plotly from './plotly';
import _factory from 'react-plotly.js/factory';
import { apiFetch } from './api';

const Plot = (_factory.default ?? _factory)(Plotly);

export default function LightCurvePanel({ layer, theme = 'dark', embedded = false }) {
  const [frequency, setFrequency] = useState('45');
  const [data, setData] = useState(null);
  const [status, setStatus] = useState('');

  async function load() {
    if (!layer) return;

    const frequencies = [...new Set(
      frequency.split(/[\s,;]+/).map(Number).filter((value) => Number.isFinite(value) && value > 0),
    )].slice(0, 8);
    if (frequencies.length === 0) {
      setStatus('Enter at least one valid frequency in MHz.');
      return;
    }

    setStatus('Loading light curve…');
    const params = new URLSearchParams({
      station: layer.station,
      date: layer.date,
      filename: layer.filename,
    });
    frequencies.forEach((value) => params.append('freq_mhz', String(value)));

    try {
      const response = await apiFetch(`/api/lightcurve?${params}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setData(await response.json());
      setStatus('');
    } catch (cause) {
      setStatus(`Could not load curve: ${cause.message}`);
    }
  }

  function close() {
    setData(null);
    setStatus('');
  }

  function exportCsv() {
    if (!data) return;
    const header = ['UTC', ...data.curves.map((curve) => `${curve.frequency_mhz} MHz (${data.unit})`)];
    const rows = data.times.map((time, index) => [
      time,
      ...data.curves.map((curve) => curve.intensity[index] ?? ''),
    ]);
    const csv = [header, ...rows].map((row) => row.map((value) => {
      const text = String(value ?? '');
      return `"${text.replaceAll('"', '""')}"`;
    }).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `light-curves-${layer.station}-${layer.date}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const plotTheme = theme === 'light'
    ? { surface: '#ffffff', text: '#26384a', grid: '#dce4ec' }
    : { surface: '#0b1726', text: '#c8d9e8', grid: '#1e3448' };

  return (
    <section className={`lightcurve-card${embedded ? ' embedded' : ''}`}>
      <p className="lightcurve-context">
        {layer ? `${layer.station} · ${layer.filename}` : 'Load a FITS block to plot its light curve.'}
      </p>
      <div className="lightcurve-toolbar">
        <div className="inline-controls">
          <label>
            Frequencies (MHz)
            <input
              type="text"
              value={frequency}
              onChange={(event) => setFrequency(event.target.value)}
              aria-describedby="lightcurve-frequency-help"
              placeholder="45, 55, 65"
            />
          </label>
          <button
            type="button"
            onClick={load}
            disabled={!layer}
            aria-expanded={Boolean(data)}
            aria-controls="lightcurve-plot"
          >
            Plot light curve
          </button>
          <span id="lightcurve-frequency-help" className="field-help">Up to eight values, separated by commas.</span>
        </div>
        {data && (
          <div className="lightcurve-actions">
            <button type="button" onClick={exportCsv}>Export CSV</button>
            <button
              type="button"
              className="lightcurve-close"
              onClick={close}
              aria-label="Close light curve"
            >
              × Close curve
            </button>
          </div>
        )}
      </div>

      <div aria-live="polite">{status}</div>
      {data && (
        <div id="lightcurve-plot" className="lightcurve-plot">
          <Plot
            data={data.curves.map((curve) => ({
              type: 'scatter',
              mode: 'lines',
              x: data.times,
              y: curve.intensity,
              name: `${curve.frequency_mhz} MHz`,
            }))}
            layout={{
              autosize: true,
              height: 260,
              margin: { l: 55, r: 20, t: 20, b: 45 },
              paper_bgcolor: plotTheme.surface,
              plot_bgcolor: plotTheme.surface,
              font: { color: plotTheme.text },
              xaxis: { title: 'UTC', gridcolor: plotTheme.grid },
              yaxis: { title: data.unit, gridcolor: plotTheme.grid },
              showlegend: true,
            }}
            config={{ responsive: true, displaylogo: false }}
            useResizeHandler
            style={{ width: '100%' }}
          />
        </div>
      )}
    </section>
  );
}
