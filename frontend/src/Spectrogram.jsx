import { useState, useEffect, useRef } from 'react';
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
  layers, layerState, failedStations,
  date, showGoes, colormap, zmin, zmax,
  triggerLoad, hasLoaded, loading, error, useSahanFilter,
}) {
  const [goesData, setGoesData] = useState(null);
  const [goesStatus, setGoesStatus] = useState('');

  // ── Zoom state ───────────────────────────────────────────────────────────
  // zoomPatches: { [station]: SpectrogramResponse } — the high-res slice data
  const [zoomPatches, setZoomPatches] = useState({});
  const [isZoomed, setIsZoomed]       = useState(false);
  const [zoomFetching, setZoomFetching] = useState(false);
  const debounceRef = useRef(null);
  const lastZoomRef = useRef(null);  // deduplicate identical relayout events

  // Reset zoom whenever a new overview is loaded
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    lastZoomRef.current = null;
    setZoomPatches({});
    setIsZoomed(false);
  }, [triggerLoad]);

  // ── Fetch GOES XRS ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!hasLoaded || triggerLoad === 0) return;
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
  }, [showGoes, triggerLoad]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Zoom handlers ────────────────────────────────────────────────────────
  function handleResetZoom() {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    lastZoomRef.current = null;
    setZoomPatches({});
    setIsZoomed(false);
  }

  async function fetchZoomPatches(x0, x1, y0, y1, targetLayers) {
    if (targetLayers.length === 0) return;
    setZoomFetching(true);
    try {
      const results = await Promise.all(
        targetLayers.map(async (layer) => {
          const params = new URLSearchParams({
            station: layer.station,
            date: layer.date,
            filename: layer.filename,
            t0: String(x0),
            t1: String(x1),
            f0: String(Math.min(y0, y1)),
            f1: String(Math.max(y0, y1)),
            sahan_filter: String(useSahanFilter),
          });
          try {
            const res = await fetch(`${API_BASE_URL}/api/spectrogram/zoom?${params}`);
            if (!res.ok) {
              const body = await res.json().catch(() => ({}));
              console.warn('Zoom failed for', layer.station, ':', body.detail);
              return null;
            }
            return await res.json();
          } catch (err) {
            console.warn('Zoom fetch error for', layer.station, err);
            return null;
          }
        })
      );
      const patches = {};
      for (let i = 0; i < targetLayers.length; i++) {
        if (results[i]) patches[targetLayers[i].station] = results[i];
      }
      if (Object.keys(patches).length > 0) {
        setZoomPatches(patches);
        setIsZoomed(true);
      }
    } finally {
      setZoomFetching(false);
    }
  }

  function handleRelayout(eventData) {
    // Double-click / autorange resets → revert to overview
    if (
      eventData['xaxis.autorange'] === true ||
      eventData['yaxis.autorange'] === true ||
      eventData['autosize'] === true
    ) {
      if (isZoomed) handleResetZoom();
      return;
    }

    const x0 = eventData['xaxis.range[0]'] ?? eventData['xaxis.range']?.[0];
    const x1 = eventData['xaxis.range[1]'] ?? eventData['xaxis.range']?.[1];
    const y0 = eventData['yaxis.range[0]'] ?? eventData['yaxis.range']?.[0];
    const y1 = eventData['yaxis.range[1]'] ?? eventData['yaxis.range']?.[1];

    if (x0 == null || x1 == null || y0 == null || y1 == null) return;

    // Deduplicate: skip if bounds are identical to the last fetched request
    const key = `${x0}|${x1}|${y0}|${y1}`;
    if (lastZoomRef.current === key) return;
    lastZoomRef.current = key;

    // Determine which layers to zoom (visible ones with filename set)
    const targets = validLayers.filter(
      (l) => layerState[l.station]?.visible !== false && l.filename
    );
    if (targets.length === 0) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchZoomPatches(x0, x1, y0, y1, targets);
    }, 350);
  }

  // ── Layer preparation ────────────────────────────────────────────────────
  // Drop layers with empty/malformed axes — prevents Plotly from stretching the
  // X-axis across months when a secondary station returned stale/mismatched data.
  const validLayers = layers.filter(
    (l) =>
      Array.isArray(l.time_axis) && l.time_axis.length > 0 &&
      Array.isArray(l.freq_axis) && l.freq_axis.length > 0
  );

  // ── Visible layers (for GOES time-clip and colorbar placement) ───────────
  const visibleLayers = validLayers.filter(
    (l) => layerState[l.station]?.visible !== false
  );

  // ── Plotly traces ────────────────────────────────────────────────────────
  const traces = [];

  validLayers.forEach((layer) => {
    // When zoomed, swap in the high-res patch for this layer if available
    const patch = isZoomed ? zoomPatches[layer.station] : null;
    const src = patch ?? layer;

    const ls = layerState[layer.station] ?? { visible: true, opacity: 1 };
    const isFirstVisible = visibleLayers[0]?.station === layer.station;
    const layerZmin = zmin !== null ? zmin : src.vmin;
    const layerZmax = zmax !== null ? zmax : src.vmax;

    traces.push({
      type: 'heatmap',
      x: src.time_axis,
      y: src.freq_axis,
      z: src.z,
      zmin: layerZmin,
      zmax: layerZmax,
      colorscale: COLORSCALES[colormap] ?? COLORSCALES.hot,
      opacity: ls.opacity,
      visible: ls.visible,
      name: layer.station,
      showscale: isFirstVisible,
      colorbar: isFirstVisible ? {
        title: { text: 'dB', side: 'right' },
        tickfont: { color: '#aaaaaa', size: 10 },
        titlefont: { color: '#aaaaaa', size: 11 },
        x: 0.88,
        bgcolor: 'rgba(0,0,0,0)',
        outlinewidth: 0,
      } : undefined,
      hovertemplate: `<b>${layer.station}</b><br>%{x}<br>%{y} MHz<br>%{z:.2f} dB<extra></extra>`,
      yaxis: 'y',
      xaxis: 'x',
    });
  });

  // ── GOES overlay — time window is the UNION of all visible layers ─────────
  if (goesData?.available && goesData.xrsb?.length > 0 && visibleLayers.length > 0) {
    const satLabel = goesData.satellite ? `GOES-${goesData.satellite}` : 'GOES';

    // Use patch time range if zoomed, otherwise full layer range
    const getSrcFor = (l) => (isZoomed && zoomPatches[l.station]) ? zoomPatches[l.station] : l;

    const tStart = visibleLayers
      .map((l) => getSrcFor(l).time_axis[0])
      .reduce((a, b) => (a < b ? a : b));
    const tEnd = visibleLayers
      .map((l) => { const s = getSrcFor(l); return s.time_axis[s.time_axis.length - 1]; })
      .reduce((a, b) => (a > b ? a : b));

    const gTimes = [];
    const gFlux = [];
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

  const hasGoesTrace = traces.some((t) => t.yaxis === 'y2');

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
    ...(hasGoesTrace ? {
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

  // ── Header title ─────────────────────────────────────────────────────────
  const headerTitle = (() => {
    if (layers.length === 0) return 'e-CALLISTO Spain · Solar Spectrogram Portal';
    if (layers.length === 1) return `${layers[0].station} · ${layers[0].date}`;
    return `${layers.length} stations · ${layers[0].date}`;
  })();

  return (
    <>
      <div className="main-header">
        <h2>
          {headerTitle}
          {useSahanFilter && layers.length > 0 && (
            <span style={{ marginLeft: '0.6rem', fontSize: '0.7rem', color: '#38bdf8' }}>
              ▶ RFI cleaning active
            </span>
          )}
          {zoomFetching && (
            <span style={{ marginLeft: '0.6rem', fontSize: '0.7rem', color: '#a3e635' }}>
              ⟳ loading high-res…
            </span>
          )}
          {isZoomed && !zoomFetching && (
            <span style={{ marginLeft: '0.6rem', fontSize: '0.7rem', color: '#4ade80' }}>
              ⤢ high-res
            </span>
          )}
        </h2>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {isZoomed && (
            <button className="btn-reset-zoom" onClick={handleResetZoom}>
              ↩ Overview
            </button>
          )}
          {layers.length === 1 && (
            <span className="file-badge">{layers[0].filename}</span>
          )}
        </div>
      </div>

      <div className="plot-area">
        {/* Empty state before first Load */}
        {!hasLoaded && !loading && layers.length === 0 && !error && (
          <div className="status-message">
            <span>Select a station and date, then press Load.</span>
          </div>
        )}

        {/* Spinner */}
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
        {validLayers.length > 0 && !loading && (
          <Plot
            data={traces}
            layout={layout}
            config={{ responsive: true, displayModeBar: true, displaylogo: false }}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
            onRelayout={handleRelayout}
          />
        )}
      </div>
    </>
  );
}
