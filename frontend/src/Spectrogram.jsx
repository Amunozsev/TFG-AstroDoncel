import { useState, useEffect } from 'react';
import Plotly from 'plotly.js-dist';
import _factory from 'react-plotly.js/factory';

const Plot = (_factory.default ?? _factory)(Plotly);

const API_BASE_URL = 'http://localhost:8000';

// All colorscales defined as explicit RGB arrays so they work regardless of the
// Plotly.js bundle version. Mirrors the colormap set in Sahan's FITS Analyzer.
const COLORSCALES = {
  // black → red → yellow → white (matplotlib "hot", standard in e-CALLISTO publications)
  hot: [
    [0.00, '#000000'], [0.33, '#cc0000'],
    [0.67, '#ffcc00'], [1.00, '#ffffff'],
  ],
  // Observatory standard: the colormap used across e-CALLISTO tools and viewer pages.
  // dark navy → blue/indigo → purple → red → orange → golden yellow → light yellow
  observatory: [
    [0.00, '#000000'], [0.10, '#0a0038'], [0.20, '#1a0080'],
    [0.30, '#4a0090'], [0.40, '#7a0080'], [0.50, '#aa2050'],
    [0.60, '#cc0000'], [0.70, '#e06000'], [0.80, '#f5a000'],
    [0.90, '#ffcc00'], [1.00, '#ffffb0'],
  ],
  // Exact matplotlib samples (11 stops each)
  viridis: [
    [0.0, '#440154'], [0.1, '#482374'], [0.2, '#404387'],
    [0.3, '#345e8d'], [0.4, '#29788e'], [0.5, '#20908c'],
    [0.6, '#22a784'], [0.7, '#44be70'], [0.8, '#79d151'],
    [0.9, '#bdde26'], [1.0, '#fde724'],
  ],
  plasma: [
    [0.0, '#0c0786'], [0.1, '#40039c'], [0.2, '#6a00a7'],
    [0.3, '#8f0da3'], [0.4, '#b02a8f'], [0.5, '#cb4777'],
    [0.6, '#e06461'], [0.7, '#f2844b'], [0.8, '#fca635'],
    [0.9, '#fcce25'], [1.0, '#eff821'],
  ],
  inferno: [
    [0.0, '#000003'], [0.1, '#160b39'], [0.2, '#410967'],
    [0.3, '#6a176e'], [0.4, '#932567'], [0.5, '#bb3754'],
    [0.6, '#dc5039'], [0.7, '#f37719'], [0.8, '#fba40a'],
    [0.9, '#f5d745'], [1.0, '#fcfea4'],
  ],
  magma: [
    [0.0, '#000003'], [0.1, '#140d35'], [0.2, '#3b0f6f'],
    [0.3, '#63197f'], [0.4, '#8c2980'], [0.5, '#b63679'],
    [0.6, '#dd4968'], [0.7, '#f6705b'], [0.8, '#fd9f6c'],
    [0.9, '#fdcf92'], [1.0, '#fbfcbf'],
  ],
  cividis: [
    [0.0, '#00224d'], [0.1, '#083370'], [0.2, '#35456c'],
    [0.3, '#4e566c'], [0.4, '#666970'], [0.5, '#7c7b78'],
    [0.6, '#948e77'], [0.7, '#aea271'], [0.8, '#c8b765'],
    [0.9, '#e4ce51'], [1.0, '#fde737'],
  ],
  turbo: [
    [0.0, '#30123b'], [0.1, '#4458cb'], [0.2, '#3e9bfe'],
    [0.3, '#18d5cc'], [0.4, '#46f783'], [0.5, '#a4fc3b'],
    [0.6, '#e1dc37'], [0.7, '#fda330'], [0.8, '#ef5a11'],
    [0.9, '#c32402'], [1.0, '#7a0402'],
  ],
  jet: [
    [0.0, '#00007f'], [0.1, '#0000f1'], [0.2, '#004cff'],
    [0.3, '#00b0ff'], [0.4, '#29ffcd'], [0.5, '#7cff79'],
    [0.6, '#cdff29'], [0.7, '#ffc400'], [0.8, '#ff6700'],
    [0.9, '#f10700'], [1.0, '#7f0000'],
  ],
  // RdYlBu reversed so that high intensity maps to red (more intuitive for spectrograms)
  rdylbu: [
    [0.0, '#313695'], [0.1, '#4473b3'], [0.2, '#74add1'],
    [0.3, '#a9d8e8'], [0.4, '#e0f3f7'], [0.5, '#fefec0'],
    [0.6, '#fee090'], [0.7, '#fcac60'], [0.8, '#f46d43'],
    [0.9, '#d62f26'], [1.0, '#a50026'],
  ],
  cubehelix: [
    [0.0, '#000000'], [0.1, '#19142f'], [0.2, '#153c4d'],
    [0.3, '#1e6542'], [0.4, '#53792e'], [0.5, '#a1794a'],
    [0.6, '#cf7e92'], [0.7, '#cf9dda'], [0.8, '#c1caf3'],
    [0.9, '#d2eeee'], [1.0, '#ffffff'],
  ],
  // bone_r: white (low) → dark blue-gray (high), good for inverted display
  bone_r: [
    [0.0, '#ffffff'], [0.1, '#dce9e9'], [0.2, '#b9d2d2'],
    [0.3, '#9cb8bc'], [0.4, '#8599a5'], [0.5, '#6f7a8e'],
    [0.6, '#595c79'], [0.7, '#42425c'], [0.8, '#2c2c3e'],
    [0.9, '#15151e'], [1.0, '#000000'],
  ],
};

export default function Spectrogram({
  station, date, filename, useSahanFilter, showGoes,
  colormap, zmin, zmax, triggerLoad, onDataLoaded,
}) {
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState(null);
  const [plotData, setPlotData]     = useState(null);
  const [goesData, setGoesData]     = useState(null);
  const [goesStatus, setGoesStatus] = useState('');

  // ── Fetch spectrogram ────────────────────────────────────────────────────
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
      setGoesStatus('Loading GOES…');
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
        setGoesStatus(`GOES unavailable: ${err.message}`);
      }
    }
    fetchGoes();
  }, [showGoes, date, triggerLoad]);

  // ── Scale values ─────────────────────────────────────────────────────────
  const finalZmin = zmin !== null ? zmin : plotData?.vmin;
  const finalZmax = zmax !== null ? zmax : plotData?.vmax;

  // ── Plotly traces ────────────────────────────────────────────────────────
  const traces = [];

  if (plotData) {
    traces.push({
      type: 'heatmap',
      x: plotData.time_axis,
      y: plotData.freq_axis,
      z: plotData.z,
      zmin: finalZmin,
      zmax: finalZmax,
      colorscale: COLORSCALES[colormap] ?? COLORSCALES.hot,
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

  if (goesData?.available && goesData.xrsb?.length > 0 && plotData?.time_axis?.length > 0) {
    const satLabel = goesData.satellite ? `GOES-${goesData.satellite}` : 'GOES';

    // Clip GOES data to the spectrogram time window (ISO 8601 string comparison is safe)
    const tStart = plotData.time_axis[0];
    const tEnd   = plotData.time_axis[plotData.time_axis.length - 1];
    const gTimes = [];
    const gFlux  = [];
    for (let i = 0; i < goesData.times.length; i++) {
      if (goesData.times[i] >= tStart && goesData.times[i] <= tEnd) {
        gTimes.push(goesData.times[i]);
        gFlux.push(goesData.xrsb[i]);
      }
    }

    if (gTimes.length > 0) {
      traces.push({
        type: 'scattergl',
        x: gTimes,
        y: gFlux,
        mode: 'lines',
        name: `${satLabel} XRS-B (0.1–0.8 nm)`,
        line: { color: '#f87171', width: 1.5 },
        yaxis: 'y2',
        xaxis: 'x',
        hovertemplate: '%{x}<br>%{y:.2e} W/m²<extra>' + satLabel + '</extra>',
      });
    }
  }

  const layout = {
    paper_bgcolor: '#080d12',
    plot_bgcolor: '#080d12',
    margin: { t: 20, r: 110, b: 60, l: 70 },
    xaxis: {
      title: { text: 'Time (UTC)', font: { color: '#7fb3d3' } },
      tickfont: { color: '#4a7a9b', size: 10 },
      gridcolor: '#1a2f46',
      linecolor: '#1a2f46',
    },
    yaxis: {
      title: { text: 'Frequency (MHz)', font: { color: '#7fb3d3' } },
      tickfont: { color: '#4a7a9b', size: 10 },
      gridcolor: '#1a2f46',
      linecolor: '#1a2f46',
    },
    ...(traces.length > 1 ? {
      yaxis2: {
        title: { text: 'GOES Flux (W/m²)', font: { color: '#f87171', size: 11 } },
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
          {plotData ? `${plotData.station} · ${plotData.date}` : 'Solar Spectrogram e-CALLISTO'}
          {useSahanFilter && (
            <span style={{ marginLeft: '0.6rem', fontSize: '0.7rem', color: '#38bdf8' }}>
              ▶ RFI cleaning active
            </span>
          )}
        </h2>
        {plotData && (
          <span className="file-badge">{plotData.filename}</span>
        )}
      </div>

      <div className="plot-area">
        {/* Global spinner while the spectrogram loads */}
        {loading && (
          <div className="status-message">
            <div className="spinner" />
            <span>Processing astronomical data…</span>
            <span style={{ fontSize: '0.72rem', color: '#2e5575', marginTop: '0.25rem' }}>
              (auto-download if file is not local)
            </span>
          </div>
        )}

        {/* Error */}
        {error && !loading && (
          <div className="status-message">
            <div className="error-message">{error}</div>
          </div>
        )}

        {/* GOES no-data notice */}
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

        {/* Chart */}
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
