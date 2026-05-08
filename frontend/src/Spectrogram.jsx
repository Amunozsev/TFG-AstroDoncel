import { useState } from 'react';
import Plotly from 'plotly.js-dist';
import _factory from 'react-plotly.js/factory';

const Plot = (_factory.default ?? _factory)(Plotly);

const API_BASE_URL = 'http://localhost:8000';

const today = new Date().toISOString().slice(0, 10);

export default function Spectrogram() {
  const [station, setStation] = useState('SPAIN-SIGUENZA');
  const [date, setDate] = useState(today);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [plotData, setPlotData] = useState(null);

  async function fetchSpectrogram() {
    setLoading(true);
    setError(null);
    try {
      const url = `${API_BASE_URL}/api/spectrogram?station=${encodeURIComponent(station)}&date=${encodeURIComponent(date)}`;
      const res = await fetch(url);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Error ${res.status}`);
      }
      const data = await res.json();
      setPlotData(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', padding: '1rem', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-end', marginBottom: '1rem', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', fontWeight: 600 }}>
          Estación
          <input
            type="text"
            value={station}
            onChange={(e) => setStation(e.target.value)}
            style={{ marginTop: '0.25rem', padding: '0.4rem 0.6rem', border: '1px solid #ccc', borderRadius: '4px', fontSize: '0.9rem' }}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', fontSize: '0.85rem', fontWeight: 600 }}>
          Fecha
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            style={{ marginTop: '0.25rem', padding: '0.4rem 0.6rem', border: '1px solid #ccc', borderRadius: '4px', fontSize: '0.9rem' }}
          />
        </label>
        <button
          onClick={fetchSpectrogram}
          disabled={loading}
          style={{
            padding: '0.45rem 1.2rem',
            background: '#1d4ed8',
            color: '#fff',
            border: 'none',
            borderRadius: '4px',
            fontSize: '0.9rem',
            cursor: loading ? 'not-allowed' : 'pointer',
            opacity: loading ? 0.7 : 1,
          }}
        >
          {loading ? 'Cargando…' : 'Cargar espectrograma'}
        </button>
      </div>

      {error && (
        <p style={{ color: '#b91c1c', background: '#fef2f2', padding: '0.5rem 0.75rem', borderRadius: '4px', marginBottom: '0.75rem' }}>
          {error}
        </p>
      )}

      {plotData && (
        <div style={{ flex: 1, minHeight: 0 }}>
          <Plot
            data={[
              {
                type: 'heatmapgl',
                x: plotData.time_axis,
                y: plotData.freq_axis,
                z: plotData.z,
                zmin: plotData.vmin,
                zmax: plotData.vmax,
                colorscale: 'Viridis',
              },
            ]}
            layout={{
              title: { text: 'Espectrograma Solar e-Callisto' },
              xaxis: { title: 'Tiempo (UTC)' },
              yaxis: { autorange: 'reversed', title: 'Frecuencia (MHz)' },
              autosize: true,
            }}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
          />
        </div>
      )}

      {!plotData && !loading && !error && (
        <p style={{ color: '#6b7280', marginTop: '2rem', textAlign: 'center' }}>
          Selecciona estación y fecha, luego pulsa «Cargar espectrograma».
        </p>
      )}
    </div>
  );
}
