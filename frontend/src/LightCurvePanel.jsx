import { useState } from 'react';
import Plotly from 'plotly.js-dist';
import _factory from 'react-plotly.js/factory';
import { apiFetch } from './api';

const Plot = (_factory.default ?? _factory)(Plotly);

export default function LightCurvePanel({ layer }) {
  const [frequency, setFrequency] = useState('45');
  const [data, setData] = useState(null);
  const [status, setStatus] = useState('');
  async function load() {
    if (!layer) return;
    setStatus('Loading light curve…');
    const params = new URLSearchParams({ station: layer.station, date: layer.date, filename: layer.filename });
    params.append('freq_mhz', frequency);
    try {
      const response = await apiFetch(`/api/lightcurve?${params}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setData(await response.json()); setStatus('');
    } catch (cause) { setStatus(`Could not load curve: ${cause.message}`); }
  }
  return <section className="lightcurve-card"><div className="inline-controls"><label>Frequency (MHz)<input type="number" step="0.1" value={frequency} onChange={(event) => setFrequency(event.target.value)} /></label><button onClick={load} disabled={!layer}>Plot light curve</button></div><div aria-live="polite">{status}</div>{data && <Plot data={data.curves.map((curve) => ({ type: 'scatter', mode: 'lines', x: data.times, y: curve.intensity, name: `${curve.frequency_mhz} MHz` }))} layout={{ autosize: true, height: 260, margin: { l: 55, r: 20, t: 20, b: 45 }, paper_bgcolor: '#0b1726', plot_bgcolor: '#0b1726', font: { color: '#c8d9e8' }, xaxis: { title: 'UTC' }, yaxis: { title: data.unit }, showlegend: true }} config={{ responsive: true, displaylogo: false }} useResizeHandler style={{ width: '100%' }} />}</section>;
}
