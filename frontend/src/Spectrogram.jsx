import { useState, useEffect } from 'react';
import Plotly from 'plotly.js-dist';
import _factory from 'react-plotly.js/factory';

const Plot = (_factory.default ?? _factory)(Plotly);

const API_BASE_URL = 'http://localhost:8000';

export default function Spectrogram({ station, date, useSahanFilter, triggerLoad }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [plotData, setPlotData] = useState(null);
  const [filePath, setFilePath] = useState('');

  useEffect(() => {
    async function fetchSpectrogram() {
      setLoading(true);
      setError(null);
      try {
        const url =
          `${API_BASE_URL}/api/spectrogram` +
          `?station=${encodeURIComponent(station)}` +
          `&date=${encodeURIComponent(date)}` +
          `&sahan_filter=${useSahanFilter}`;

        const res = await fetch(url);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail ?? `Error ${res.status}`);
        }
        const data = await res.json();
        setPlotData(data);
        // Extraer nombre de archivo del header si existe
        setFilePath(data.filename ?? '');
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }

    fetchSpectrogram();
  }, [station, date, useSahanFilter, triggerLoad]);

  return (
    <>
      <div className="main-header">
        <h2>
          Espectrograma Solar · {station}
          {useSahanFilter && <span style={{ marginLeft: '0.6rem', fontSize: '0.72rem', color: '#38bdf8' }}>▶ filtro Sahan activo</span>}
        </h2>
        {filePath && <span className="file-badge">{filePath}</span>}
      </div>

      <div className="plot-area">
        {loading && (
          <div className="status-message">
            <div className="spinner" />
            <span>Cargando datos astronómicos…</span>
          </div>
        )}

        {error && !loading && (
          <div className="status-message">
            <div className="error-message">{error}</div>
          </div>
        )}

        {plotData && !loading && (
          <Plot
            data={[
              {
                type: 'heatmap',
                x: plotData.time_axis,
                y: plotData.freq_axis,
                z: plotData.z,
                zmin: plotData.vmin,
                zmax: plotData.vmax,
                colorscale: 'Viridis',
                colorbar: {
                  title: { text: 'Intensidad', side: 'right' },
                  tickfont: { color: '#7fb3d3', size: 10 },
                  titlefont: { color: '#7fb3d3', size: 11 },
                },
              },
            ]}
            layout={{
              paper_bgcolor: '#080d12',
              plot_bgcolor: '#080d12',
              margin: { t: 20, r: 80, b: 60, l: 70 },
              xaxis: {
                title: { text: 'Tiempo (UTC)', font: { color: '#7fb3d3' } },
                tickfont: { color: '#4a7a9b', size: 10 },
                gridcolor: '#1a2f46',
                linecolor: '#1a2f46',
              },
              yaxis: {
                title: { text: 'Frecuencia (MHz)', font: { color: '#7fb3d3' } },
                autorange: 'reversed',
                tickfont: { color: '#4a7a9b', size: 10 },
                gridcolor: '#1a2f46',
                linecolor: '#1a2f46',
              },
              autosize: true,
            }}
            config={{ responsive: true, displayModeBar: true, displaylogo: false }}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
          />
        )}
      </div>
    </>
  );
}
