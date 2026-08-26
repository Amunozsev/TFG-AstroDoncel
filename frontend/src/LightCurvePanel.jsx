import { useEffect, useRef, useState } from 'react';
import { Plot } from './plotly';
import { apiFetch } from './api';

function exportCsv(result) {
  const { data, source } = result;
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
  link.download = `light-curves-${source.station}-${source.date}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

export function LightCurveResult({ result, theme = 'dark', timeRange, onClose }) {
  const sectionRef = useRef(null);
  const { data, source } = result;

  useEffect(() => {
    sectionRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }, [result]);

  const plotTheme = theme === 'light'
    ? { surface: '#f7f9fc', text: '#3f5870', grid: '#d8e1ea' }
    : { surface: '#080d12', text: '#c8d9e8', grid: '#1e3448' };

  return (
    <section id="lightcurve-result" ref={sectionRef} className="lightcurve-result" aria-label="Light curve aligned with the spectrogram">
      <header>
        <div>
          <span className="section-kicker">Aligned UTC view</span>
          <h2>Light curve</h2>
          <p>{source.station} · {source.filename} · {data.unit}</p>
        </div>
        <div className="lightcurve-actions">
          <button type="button" onClick={() => exportCsv(result)}>Export CSV</button>
          <button type="button" className="lightcurve-close" onClick={onClose} aria-label="Close light curve">
            Close curve
          </button>
        </div>
      </header>
      <div className="lightcurve-plot">
        <Plot
          data={data.curves.map((curve) => ({
            type: 'scatter',
            mode: 'lines',
            x: data.times,
            y: curve.intensity,
            name: `${curve.frequency_mhz} MHz`,
            line: { width: 1.6 },
          }))}
          layout={{
            autosize: true,
            height: 280,
            margin: { l: 70, r: 110, t: 18, b: 55 },
            paper_bgcolor: plotTheme.surface,
            plot_bgcolor: plotTheme.surface,
            font: { color: plotTheme.text },
            xaxis: { title: 'Time (UTC)', type: 'date', range: timeRange, gridcolor: plotTheme.grid },
            yaxis: { title: data.unit, gridcolor: plotTheme.grid },
            legend: { orientation: 'h', x: 0, y: 1.12 },
            showlegend: true,
          }}
          config={{ responsive: true, displaylogo: false }}
          useResizeHandler
          style={{ width: '100%' }}
        />
      </div>
    </section>
  );
}

export default function LightCurvePanel({ layer, theme = 'dark', embedded = false, onCurve }) {
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
      const payload = await response.json();
      const result = {
        data: payload,
        source: { station: layer.station, date: layer.date, filename: layer.filename },
      };
      setData(result);
      onCurve?.(result);
      setStatus(onCurve ? 'Curve displayed below the spectrogram.' : '');
    } catch (cause) {
      setStatus(`Could not load curve: ${cause.message}`);
    }
  }

  function close() {
    setData(null);
    setStatus('');
  }

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
      </div>

      <div aria-live="polite">{status}</div>
      {data && !embedded && <LightCurveResult result={data} theme={theme} onClose={close} />}
    </section>
  );
}
