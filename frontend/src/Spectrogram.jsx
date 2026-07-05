import { useState, useEffect, useRef, useCallback } from 'react';
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

const AXIS_STYLE = {
  tickfont: { color: '#4a7a9b', size: 10 },
  gridcolor: '#1a2f46',
  linecolor: '#1a2f46',
};

function hexToRgbTuple(hex) {
  const h = hex.replace('#', '');
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

/**
 * Convert a hex colorscale into an rgba colorscale whose alpha grows with
 * intensity: fully transparent at the low end, maxAlpha at the high end.
 * This is what makes translucent overlay of several stations work — the dark
 * background of upper layers no longer hides the layers underneath; only
 * bright features (bursts) blend on top.
 */
function alphaColorscale(scale, maxAlpha = 0.85) {
  return scale.map(([t, c]) => {
    const [r, g, b] = hexToRgbTuple(c);
    const a = t <= 0 ? 0 : +(Math.pow(t, 0.75) * maxAlpha).toFixed(3);
    return [t, `rgba(${r},${g},${b},${a})`];
  });
}

/** Plotly axis id for panel index i: y, y2, y3, ... */
const panelAxisId = (i) => (i === 0 ? 'y' : `y${i + 1}`);
const panelAxisKey = (i) => (i === 0 ? 'yaxis' : `yaxis${i + 1}`);

export default function Spectrogram({
  layers, layerState, failedStations,
  date, showGoes, colormap, zmin, zmax,
  triggerLoad, hasLoaded, loading, error,
  useSahanFilter, rfiParams,
  compareMode, autoContrastZoom, rulerMode,
  burstResults,
}) {
  const [goesData, setGoesData] = useState(null);
  const [goesStatus, setGoesStatus] = useState('');

  // ── Zoom state ───────────────────────────────────────────────────────────
  // zoomPatches: { [station]: SpectrogramResponse } — the high-res slice data
  const [zoomPatches, setZoomPatches] = useState({});
  const [isZoomed, setIsZoomed]       = useState(false);
  const [zoomFetching, setZoomFetching] = useState(false);
  // Bumping resetRev changes uirevision → Plotly autoranges all axes.
  const [resetRev, setResetRev]       = useState(0);
  const debounceRef = useRef(null);
  const lastZoomRef = useRef(null);       // deduplicate identical range states
  const abortRef    = useRef(null);       // cancel in-flight zoom fetches
  // Accumulated view state: x range + y range per axis id ('y', 'y2', ...).
  // Plotly relayout events are incremental (x-only or y-only), so we merge.
  const viewRef     = useRef({ x: null, yByAxis: {} });

  // ── Ruler (drift measurement) state ──────────────────────────────────────
  const [rulerPoints, setRulerPoints] = useState([]);

  function clearZoomState() {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) abortRef.current.abort();
    lastZoomRef.current = null;
    viewRef.current = { x: null, yByAxis: {} };
    setZoomPatches({});
    setIsZoomed(false);
    setZoomFetching(false);
  }

  // Reset zoom + ruler whenever a new overview is loaded or the mode changes
  useEffect(() => {
    clearZoomState();
    setRulerPoints([]);
  }, [triggerLoad, compareMode]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setRulerPoints([]);
  }, [rulerMode]);

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

  // ── Layer preparation ────────────────────────────────────────────────────
  // Drop layers with empty/malformed axes — prevents Plotly from stretching the
  // X-axis across months when a secondary station returned stale/mismatched data.
  const validLayers = layers.filter(
    (l) =>
      Array.isArray(l.time_axis) && l.time_axis.length > 0 &&
      Array.isArray(l.freq_axis) && l.freq_axis.length > 0
  );

  const visibleLayers = validLayers.filter(
    (l) => layerState[l.station]?.visible !== false
  );

  // In panels mode each visible layer owns one stacked subplot (top → bottom).
  const panelLayers = compareMode === 'panels' ? visibleLayers : [];
  const axisIdByStation = {};
  panelLayers.forEach((l, i) => { axisIdByStation[l.station] = panelAxisId(i); });

  // ── Zoom handlers ────────────────────────────────────────────────────────
  function handleResetZoom() {
    clearZoomState();
    setResetRev((n) => n + 1); // new uirevision → Plotly autoranges
  }

  async function fetchZoomPatches(requests) {
    if (requests.length === 0) return;
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setZoomFetching(true);
    try {
      const results = await Promise.all(
        requests.map(async ({ layer, t0, t1, f0, f1 }) => {
          const params = new URLSearchParams({
            station: layer.station,
            date: layer.date,
            filename: layer.filename,
            t0: String(t0),
            t1: String(t1),
            f0: String(Math.min(f0, f1)),
            f1: String(Math.max(f0, f1)),
            sahan_filter: String(useSahanFilter),
            rfi_z_thresh: String(rfiParams?.zThresh ?? 6.0),
            rfi_occupancy: String(rfiParams?.occupancy ?? 0.15),
            rfi_min_component: String(rfiParams?.minComponent ?? 9),
            rfi_impulsive: String(rfiParams?.impulsive ?? true),
          });
          try {
            const res = await fetch(
              `${API_BASE_URL}/api/spectrogram/zoom?${params}`,
              { signal: ctrl.signal }
            );
            if (!res.ok) {
              const body = await res.json().catch(() => ({}));
              console.warn('Zoom failed for', layer.station, ':', body.detail);
              return null;
            }
            return await res.json();
          } catch (err) {
            if (err.name !== 'AbortError') {
              console.warn('Zoom fetch error for', layer.station, err);
            }
            return null;
          }
        })
      );
      if (ctrl.signal.aborted) return; // superseded by a newer zoom
      const patches = {};
      for (let i = 0; i < requests.length; i++) {
        if (results[i]) patches[requests[i].layer.station] = results[i];
      }
      if (Object.keys(patches).length > 0) {
        setZoomPatches(patches);
        setIsZoomed(true);
      }
    } finally {
      if (abortRef.current === ctrl) setZoomFetching(false);
    }
  }

  function handleRelayout(eventData) {
    if (!eventData || validLayers.length === 0) return;

    // Double-click / autorange resets → revert to overview
    const autoranged = Object.entries(eventData).some(
      ([k, v]) => k.endsWith('.autorange') && v === true
    );
    if (autoranged || eventData['autosize'] === true) {
      if (isZoomed) handleResetZoom();
      else viewRef.current = { x: null, yByAxis: {} };
      return;
    }

    // Extract range updates (both 'xaxis.range[0]' and 'xaxis.range' forms).
    const getPair = (prefix) => {
      const arr = eventData[`${prefix}.range`];
      if (Array.isArray(arr) && arr.length === 2) return [arr[0], arr[1]];
      const a = eventData[`${prefix}.range[0]`];
      const b = eventData[`${prefix}.range[1]`];
      return a != null && b != null ? [a, b] : null;
    };

    let touched = false;
    const v = viewRef.current;
    const xr = getPair('xaxis');
    if (xr) { v.x = xr; touched = true; }
    for (let i = 0; i < 8; i++) {
      const yr = getPair(panelAxisKey(i));
      if (yr) { v.yByAxis[panelAxisId(i)] = yr; touched = true; }
    }
    if (!touched) return; // pure redraw / legend / dragmode event — ignore

    // Deduplicate: skip if the accumulated view is identical to the last fetch
    const key = JSON.stringify(v);
    if (lastZoomRef.current === key) return;
    lastZoomRef.current = key;

    const targets = visibleLayers.filter((l) => l.filename);
    if (targets.length === 0) return;

    // Build one request per layer; missing bounds fall back to the layer's
    // full extent (e.g. y-only zoom still refetches the full time range).
    const requests = targets.map((layer) => {
      const axisId = compareMode === 'panels'
        ? (axisIdByStation[layer.station] ?? 'y')
        : 'y';
      const yr = v.yByAxis[axisId] ?? null;
      const t0 = v.x ? v.x[0] : layer.time_axis[0];
      const t1 = v.x ? v.x[1] : layer.time_axis[layer.time_axis.length - 1];
      let f0, f1;
      if (yr) {
        [f0, f1] = yr;
      } else {
        f0 = Math.min(...layer.freq_axis);
        f1 = Math.max(...layer.freq_axis);
      }
      return { layer, t0, t1, f0, f1 };
    });

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchZoomPatches(requests);
    }, 300);
  }

  // ── Ruler click handler ──────────────────────────────────────────────────
  function handlePlotClick(ev) {
    if (!rulerMode || !ev?.points?.length) return;
    const pt = ev.points[0];
    if (pt.x == null || pt.y == null) return;
    const yref = pt.data?.yaxis || 'y';
    setRulerPoints((prev) =>
      prev.length >= 2 ? [{ x: pt.x, y: pt.y, yref }] : [...prev, { x: pt.x, y: pt.y, yref }]
    );
  }

  // react-plotly's own event binding (onRelayout/onClick props) silently loses
  // the listeners after figure updates with plotly.js 3.x — this was the root
  // cause of the unreliable high-res zoom. We bind manually on the graph div
  // instead, re-attaching after every plot update (onInitialized + onUpdate run
  // on the exact same code path that keeps react-plotly's internal sync alive).
  // Handlers dereference refs so the latest closure always runs (no staleness).
  const relayoutRef = useRef(null);
  relayoutRef.current = handleRelayout;
  const clickRef = useRef(null);
  clickRef.current = handlePlotClick;
  const onRelayoutStable = useCallback((e) => relayoutRef.current?.(e), []);
  const onClickStable = useCallback((e) => clickRef.current?.(e), []);
  const bindPlotEvents = useCallback((_figure, gd) => {
    if (!gd?.on) return;
    // Idempotent: drop then re-add, so repeated onUpdate calls never stack
    gd.removeListener?.('plotly_relayout', onRelayoutStable);
    gd.removeListener?.('plotly_click', onClickStable);
    gd.on('plotly_relayout', onRelayoutStable);
    gd.on('plotly_click', onClickStable);
  }, [onRelayoutStable, onClickStable]);

  const rulerMeasure = (() => {
    if (rulerPoints.length !== 2) return null;
    const [p1, p2] = rulerPoints;
    const dtSec = (new Date(p2.x) - new Date(p1.x)) / 1000;
    const dfMHz = p2.y - p1.y;
    const drift = dtSec !== 0 ? dfMHz / dtSec : null;
    return { dtSec, dfMHz, drift };
  })();

  // ── Plotly traces ────────────────────────────────────────────────────────
  const traces = [];
  const layout = {
    paper_bgcolor: '#080d12',
    plot_bgcolor: '#080d12',
    margin: { t: 20, r: 110, b: 60, l: 70 },
    // uirevision keeps the user's zoom across data updates (hi-res patch swaps,
    // contrast/colormap tweaks). It only resets on a new load, a comparison-mode
    // switch, or an explicit "Overview" click.
    uirevision: `${triggerLoad}-${compareMode}-${resetRev}`,
    xaxis: {
      title: { text: 'Time (UTC)', font: { color: '#7fb3d3' } },
      ...AXIS_STYLE,
    },
    legend: {
      font: { color: '#7fb3d3', size: 10 },
      bgcolor: 'rgba(13,27,42,0.8)',
      x: 0.01, y: 0.99,
    },
    annotations: [],
    shapes: [],
    autosize: true,
  };

  const srcFor = (layer) => (isZoomed && zoomPatches[layer.station]) ? zoomPatches[layer.station] : layer;

  // ── ML burst-event highlights (amber boxes + score labels) ────────────────
  const addBurstShapes = (layer, axisId) => {
    const res = burstResults?.[layer.station];
    if (!res?.available || !res.events?.length) return;
    for (const ev of res.events) {
      if (!ev.start_utc || !ev.end_utc) continue;
      const isFallback = ev.source === 'visual_fallback'
        || res.event_source === 'visual_fallback'
        || res.event_source === 'visual_candidate';
      const scoreText = Number.isFinite(ev.peak_score) ? ev.peak_score.toFixed(2) : '?';
      layout.shapes.push({
        type: 'rect',
        xref: 'x',
        yref: axisId,
        x0: ev.start_utc, x1: ev.end_utc,
        y0: ev.freq_band_mhz[0], y1: ev.freq_band_mhz[1],
        line: { color: '#fbbf24', width: isFallback ? 1.25 : 1.6, dash: isFallback ? 'dash' : 'dot' },
        fillcolor: isFallback ? 'rgba(251,191,36,0.07)' : 'rgba(251,191,36,0.10)',
        layer: 'above',
      });
      layout.annotations.push({
        xref: 'x',
        yref: axisId,
        x: ev.start_utc,
        y: ev.freq_band_mhz[1],
        xanchor: 'left', yanchor: 'bottom',
        text: `${isFallback ? 'cand ' : ''}p=${scoreText}`,
        showarrow: false,
        font: { color: '#fbbf24', size: 9 },
        bgcolor: 'rgba(13,27,42,0.75)',
      });
    }
  };

  const contrastFor = (layer) => {
    const patch = isZoomed ? zoomPatches[layer.station] : null;
    const base = patch && autoContrastZoom ? patch : layer;
    return {
      zmin: zmin !== null ? zmin : base.vmin,
      zmax: zmax !== null ? zmax : base.vmax,
    };
  };

  if (compareMode === 'panels' && panelLayers.length > 0) {
    // ── Stacked synchronised panels (one subplot per station, shared UT axis).
    //    This is how Sahan's Multi-Station Comparison workspace renders — the
    //    scientifically meaningful way to compare stations with different
    //    frequency ranges.
    const N = panelLayers.length;
    const gap = N > 1 ? 0.05 : 0;
    const h = (1 - gap * (N - 1)) / N;

    panelLayers.forEach((layer, i) => {
      const src = srcFor(layer);
      const { zmin: zLo, zmax: zHi } = contrastFor(layer);
      const axisId = panelAxisId(i);
      const top = 1 - i * (h + gap);
      const bottom = top - h;

      layout[panelAxisKey(i)] = {
        title: i === Math.floor((N - 1) / 2)
          ? { text: 'Frequency (MHz)', font: { color: '#7fb3d3' } }
          : undefined,
        domain: [Math.max(0, bottom), Math.min(1, top)],
        ...AXIS_STYLE,
      };

      traces.push({
        type: 'heatmap',
        x: src.time_axis,
        y: src.freq_axis,
        z: src.z,
        zmin: zLo,
        zmax: zHi,
        colorscale: COLORSCALES[colormap] ?? COLORSCALES.hot,
        name: layer.station,
        showscale: true,
        colorbar: {
          tickfont: { color: '#aaaaaa', size: 9 },
          x: 1.02,
          y: (top + bottom) / 2,
          yanchor: 'middle',
          len: h * 0.95,
          thickness: 12,
          bgcolor: 'rgba(0,0,0,0)',
          outlinewidth: 0,
        },
        hovertemplate: `<b>${layer.station}</b><br>%{x}<br>%{y} MHz<br>%{z:.2f} dB<extra></extra>`,
        yaxis: axisId,
        xaxis: 'x',
      });

      layout.annotations.push({
        xref: 'paper', yref: 'paper',
        x: 0.005, y: top,
        xanchor: 'left', yanchor: 'top',
        text: layer.station,
        showarrow: false,
        font: { color: '#7fb3d3', size: 10 },
        bgcolor: 'rgba(13,27,42,0.75)',
      });

      addBurstShapes(layer, axisId);
    });

    // Anchor the shared time axis to the bottom panel
    layout.xaxis.anchor = panelAxisId(N - 1);
  } else {
    // ── Translucent overlay: first visible layer is the opaque base; upper
    //    layers use an alpha-graded colorscale so their low-intensity
    //    background is transparent and only bright bursts blend on top.
    layout.yaxis = {
      title: { text: 'Frequency (MHz)', font: { color: '#7fb3d3' } },
      ...AXIS_STYLE,
    };

    let visIdx = 0;
    validLayers.forEach((layer) => {
      const src = srcFor(layer);
      const ls = layerState[layer.station] ?? { visible: true, opacity: 1 };
      const { zmin: zLo, zmax: zHi } = contrastFor(layer);
      const isBase = ls.visible && visIdx === 0;
      if (ls.visible) visIdx += 1;
      const baseScale = COLORSCALES[colormap] ?? COLORSCALES.hot;

      traces.push({
        type: 'heatmap',
        x: src.time_axis,
        y: src.freq_axis,
        z: src.z,
        zmin: zLo,
        zmax: zHi,
        colorscale: isBase ? baseScale : alphaColorscale(baseScale, ls.opacity),
        opacity: isBase ? ls.opacity : 1, // upper layers carry alpha in the scale
        visible: ls.visible,
        name: layer.station,
        showscale: isBase,
        colorbar: isBase ? {
          title: { text: 'dB', side: 'right' },
          tickfont: { color: '#aaaaaa', size: 10 },
          titlefont: { color: '#aaaaaa', size: 11 },
          x: 1.02,
          thickness: 14,
          bgcolor: 'rgba(0,0,0,0)',
          outlinewidth: 0,
        } : undefined,
        hovertemplate: `<b>${layer.station}</b><br>%{x}<br>%{y} MHz<br>%{z:.2f} dB<extra></extra>`,
        yaxis: 'y',
        xaxis: 'x',
      });

      if (ls.visible) addBurstShapes(layer, 'y');
    });
  }

  // ── GOES overlay — time window is the UNION of all visible layers ─────────
  if (goesData?.available && goesData.xrsb?.length > 0 && visibleLayers.length > 0) {
    const satLabel = goesData.satellite ? `GOES-${goesData.satellite}` : 'GOES';

    const tStart = visibleLayers
      .map((l) => srcFor(l).time_axis[0])
      .reduce((a, b) => (a < b ? a : b));
    const tEnd = visibleLayers
      .map((l) => { const s = srcFor(l); return s.time_axis[s.time_axis.length - 1]; })
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
      // In panels mode the flux curve is repeated on every panel (each on its
      // own log axis overlaying that panel); in overlay mode a single curve
      // overlays the shared y axis. GOES axes start at y8 (panels use y..y6).
      const overlayTargets = compareMode === 'panels' && panelLayers.length > 0
        ? panelLayers.map((_, i) => panelAxisId(i))
        : ['y'];
      overlayTargets.forEach((targetAxis, i) => {
        const goesAxisNum = 8 + i;
        traces.push({
          // SVG scatter (not scattergl): one trace per panel would need one
          // WebGL context each, and browsers cap those. ~1k points is cheap.
          type: 'scatter',
          x: gTimes,
          y: gFlux,
          mode: 'lines',
          name: `${satLabel} XRS-B (0.1–0.8 nm)`,
          showlegend: i === 0,
          line: { color: '#f87171', width: 1.5 },
          yaxis: `y${goesAxisNum}`,
          xaxis: 'x',
          hovertemplate: '%{x}<br>%{y:.2e} W/m²<extra>' + satLabel + '</extra>',
        });
        layout[`yaxis${goesAxisNum}`] = {
          title: i === 0
            ? { text: 'GOES Flux (W/m²)', font: { color: '#f87171', size: 11 } }
            : undefined,
          overlaying: targetAxis,
          side: 'right',
          type: 'log',
          tickfont: { color: '#f87171', size: 9 },
          showticklabels: i === 0,
          showgrid: false,
          position: 0.98,
        };
      });
    }
  }

  // ── Ruler markers + measurement line ─────────────────────────────────────
  if (rulerMode && rulerPoints.length > 0) {
    traces.push({
      type: 'scatter',
      mode: 'markers',
      x: rulerPoints.map((p) => p.x),
      y: rulerPoints.map((p) => p.y),
      marker: { color: '#a3e635', size: 10, symbol: 'x' },
      yaxis: rulerPoints[0].yref,
      xaxis: 'x',
      showlegend: false,
      hoverinfo: 'skip',
    });
    if (rulerPoints.length === 2) {
      layout.shapes.push({
        type: 'line',
        xref: 'x',
        yref: rulerPoints[0].yref,
        x0: rulerPoints[0].x, y0: rulerPoints[0].y,
        x1: rulerPoints[1].x, y1: rulerPoints[1].y,
        line: { color: '#a3e635', width: 2, dash: 'dot' },
      });
    }
  }

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
              ▶ RFI v2 active
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
          {rulerMode && (
            <span style={{ marginLeft: '0.6rem', fontSize: '0.7rem', color: '#a3e635' }}>
              📐 {rulerMeasure
                ? `Δt=${rulerMeasure.dtSec.toFixed(1)} s · Δf=${rulerMeasure.dfMHz.toFixed(1)} MHz` +
                  (rulerMeasure.drift !== null ? ` · ${rulerMeasure.drift.toFixed(2)} MHz/s` : '')
                : `ruler: click ${2 - rulerPoints.length} more point${rulerPoints.length === 1 ? '' : 's'}`}
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
            <span>Select one or more stations and a date, then press Load.</span>
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

        {/* All layers hidden */}
        {validLayers.length > 0 && visibleLayers.length === 0 && !loading && (
          <div className="status-message">
            <span>All layers are hidden — enable one in the Layers tab.</span>
          </div>
        )}

        {/* Chart */}
        {visibleLayers.length > 0 && !loading && (
          <Plot
            data={traces}
            layout={layout}
            config={{ responsive: true, displayModeBar: true, displaylogo: false }}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
            onInitialized={bindPlotEvents}
            onUpdate={bindPlotEvents}
          />
        )}
      </div>
    </>
  );
}
