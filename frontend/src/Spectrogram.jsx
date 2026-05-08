import { useState, useEffect } from 'react';
import Plotly from 'plotly.js-dist';
import _factory from 'react-plotly.js/factory';

const Plot = (_factory.default ?? _factory)(Plotly);

const API_BASE_URL = 'http://localhost:8000';

// Colorscale que replica el mapa "hot" de matplotlib: negro → rojo → amarillo → blanco.
// Es el estándar en el analizador de Sahan y en publicaciones e-CALLISTO.
const HOT_COLORSCALE = [
  [0.00, '#000000'],
  [0.33, '#cc0000'],
  [0.67, '#ffcc00'],
  [1.00, '#ffffff'],
];

export default function Spectrogram({
  station, date, filename, useSahanFilter, showGoes,
  zmin, zmax, triggerLoad, onDataLoaded,
}) {
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState(null);
  const [plotData, setPlotData]     = useState(null);
  const [goesData, setGoesData]     = useState(null);
  const [goesStatus, setGoesStatus] = useState('');

  // ── Fetch espectrograma ──────────────────────────────────────────────────
  useEffect(() => {
    async function fetchSpectrogram() {
      setLoading(true);
      setError(null);
      try {
        let url =
          `${API_BASE_URL}/api/spectrogram` +
          `?station=${encodeURIComponent(station)}` +
          `&date=${encodeURIComponent(date)}` +
          `&sahan_filter=${useSahanFilter}`;
        if (filename) url += `&filename=${encodeURIComponent(filename)}`;

        const res = await fetch(url);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail ?? `Error ${res.status}`);
        }
        const data = await res.json();
        setPlotData(data);
        if (onDataLoaded) onDataLoaded(data.vmin, data.vmax);
      } catch (err) {
        setError(err.message);
        setPlotData(null);
      } finally {
        setLoading(false);
      }
    }
    fetchSpectrogram();
  }, [station, date, filename, useSahanFilter, triggerLoad]);

  // ── Fetch GOES XRS ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!showGoes) {
      setGoesData(null);
      setGoesStatus('');
      return;
    }
    async function fetchGoes() {
      setGoesStatus('Cargando GOES…');
      try {
        const url = `${API_BASE_URL}/api/goes?date=${encodeURIComponent(date)}`;
        const res = await fetch(url);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail ?? `Error GOES ${res.status}`);
        }
        const data = await res.json();
        setGoesData(data);
        setGoesStatus(data.available ? '' : data.reason);
      } catch (err) {
        setGoesData(null);
        setGoesStatus(`GOES no disponible: ${err.message}`);
      }
    }
    fetchGoes();
  }, [showGoes, date, triggerLoad]);

  // ── Valores de escala ────────────────────────────────────────────────────
  const finalZmin = zmin !== null ? zmin : plotData?.vmin;
  const finalZmax = zmax !== null ? zmax : plotData?.vmax;

  // ── Trazas Plotly ────────────────────────────────────────────────────────
  const traces = [];

  if (plotData) {
    traces.push({
      type: 'heatmap',
      x: plotData.time_axis,
      y: plotData.freq_axis,
      z: plotData.z,
      zmin: finalZmin,
      zmax: finalZmax,
      colorscale: HOT_COLORSCALE,
      colorbar: {
        title: { text: 'dB', side: 'right' },
        tickfont: { color: '#aaaaaa', size: 10 },
        titlefont: { color: '#aaaaaa', size: 11 },
        x: 0.88,
        bgcolor: 'rgba(0,0,0,0)',
        outlinewidth: 0,
      },
      yaxis: 'y',
      xaxis: 'x',
    });
  }

  if (goesData?.available && goesData.xrsb?.length > 0) {
    const satLabel = goesData.satellite ? `GOES-${goesData.satellite}` : 'GOES';
    traces.push({
      type: 'scattergl',
      x: goesData.times,
      y: goesData.xrsb,
      mode: 'lines',
      name: `${satLabel} XRS-B (0.1–0.8 nm)`,
      line: { color: '#f87171', width: 1.5 },
      yaxis: 'y2',
      xaxis: 'x',
      hovertemplate: '%{x}<br>%{y:.2e} W/m²<extra>' + satLabel + '</extra>',
    });
  }

  const layout = {
    paper_bgcolor: '#080d12',
    plot_bgcolor: '#080d12',
    margin: { t: 20, r: 110, b: 60, l: 70 },
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
    ...(goesData?.available ? {
      yaxis2: {
        title: { text: 'Flujo GOES (W/m²)', font: { color: '#f87171', size: 11 } },
        overlaying: 'y',
        side: 'right',
        type: 'log',
        tickfont: { color: '#f87171', size: 9 },
        gridcolor: 'rgba(248,113,113,0.1)',
        showgrid: false,
        position: 0.95,
      },
    } : {}),
    legend: {
      font: { color: '#7fb3d3', size: 10 },
      bgcolor: 'rgba(13,27,42,0.8)',
      x: 0.01, y: 0.99,
    },
    autosize: true,
  };

  return (
    <>
      <div className="main-header">
        <h2>
          {plotData ? `${plotData.station} · ${plotData.date}` : 'Espectrograma Solar e-CALLISTO'}
          {useSahanFilter && (
            <span style={{ marginLeft: '0.6rem', fontSize: '0.7rem', color: '#38bdf8' }}>
              ▶ RFI cleaning activo
            </span>
          )}
        </h2>
        {plotData && (
          <span className="file-badge">{plotData.filename}</span>
        )}
      </div>

      <div className="plot-area">
        {/* Spinner global mientras carga el espectrograma */}
        {loading && (
          <div className="status-message">
            <div className="spinner" />
            <span>Procesando datos astronómicos…</span>
            <span style={{ fontSize: '0.72rem', color: '#2e5575', marginTop: '0.25rem' }}>
              (descarga automática si el archivo no es local)
            </span>
          </div>
        )}

        {/* Error */}
        {error && !loading && (
          <div className="status-message">
            <div className="error-message">{error}</div>
          </div>
        )}

        {/* Aviso GOES sin datos */}
        {goesStatus && !loading && (
          <div style={{
            position: 'absolute', bottom: '0.75rem', left: '50%',
            transform: 'translateX(-50%)', zIndex: 10,
            background: '#1f1505', border: '1px solid #78350f',
            color: '#fbbf24', padding: '0.4rem 0.8rem', borderRadius: '4px',
            fontSize: '0.72rem', maxWidth: '600px', textAlign: 'center',
          }}>
            ⚠ {goesStatus}
          </div>
        )}

        {/* Gráfico */}
        {plotData && !loading && (
          <Plot
            data={traces}
            layout={layout}
            config={{ responsive: true, displayModeBar: true, displaylogo: false }}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
          />
        )}
      </div>
    </>
  );
}
