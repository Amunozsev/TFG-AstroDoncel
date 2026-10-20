import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from './api';

export const TYPE_II_COLORS = { region: '#a3e635', points: '#38bdf8', fit: '#f87171', upper: '#e879f9', lower: '#fb923c', excluded: '#64748b' };
const COLORS = TYPE_II_COLORS;

async function postJson(path, body, signal) {
  const res = await apiFetch(path, {
    method: 'POST',
    body: JSON.stringify(body),
    signal,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Error ${res.status}`);
  return data;
}

export const asPairs = (points) => points.map((p) => [String(p.x), p.y]);

/**
 * Type II analysis state shared by the spectrogram (clicks, overlays) and the
 * result panel. Clicks draw the burst region or mark split-band lanes; every
 * calculation runs in the API so the physics stays in one tested module.
 */
export function useTypeII(layer, active) {
  const fileKey = layer ? `${layer.station}:${layer.date}:${layer.filename}` : '';
  const [state, setState] = useState({ fileKey });
  const [pickMode, setPickMode] = useState(null);
  const [polygon, setPolygon] = useState([]);
  const [backbone, setBackbone] = useState(null);
  const [excluded, setExcluded] = useState(() => new Set());
  const [fold, setFold] = useState(1);
  const [harmonic, setHarmonic] = useState(false);
  const [shock, setShock] = useState(null);
  const [upper, setUpper] = useState([]);
  const [lower, setLower] = useState([]);
  const [bandInput, setBandInput] = useState(null);
  const [band, setBand] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // A new observation invalidates every point drawn on the previous one.
  if (state.fileKey !== fileKey) {
    setState({ fileKey });
    setPickMode(null); setPolygon([]); setBackbone(null); setExcluded(new Set());
    setShock(null); setUpper([]); setLower([]); setBandInput(null); setBand(null); setError(null);
  }
  const source = layer ? { station: layer.station, date: layer.date, filename: layer.filename } : null;

  const onPlotClick = useCallback((point) => {
    if (!active || !pickMode) return;
    const add = { region: setPolygon, upper: setUpper, lower: setLower }[pickMode];
    add((prev) => [...prev, point]);
  }, [active, pickMode]);

  async function analyzeRegion() {
    setBusy(true);
    setError(null);
    setPickMode(null);
    try {
      const data = await postJson('/api/type2/backbone', {
        ...source, polygon: asPairs(polygon), rfi: layer.rfi, scale_mode: layer.scale_mode ?? 'relative',
      });
      setExcluded(new Set());
      setBackbone(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // Refit whenever the points, the fold or the emission mode change.
  useEffect(() => {
    if (!backbone) return undefined;
    const controller = new AbortController();
    const points = backbone.time_utc
      .map((time, i) => [time, backbone.freq_mhz[i]])
      .filter((_, i) => !excluded.has(i));
    postJson('/api/type2/shock', { ...source, points, fold, harmonic }, controller.signal)
      .then((data) => { setShock(data); setError(null); })
      .catch((err) => { if (!controller.signal.aborted) { setShock(null); setError(err.message); } });
    return () => controller.abort();
  }, [backbone, excluded, fold, harmonic]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!bandInput) return undefined;
    const controller = new AbortController();
    postJson('/api/type2/band-splitting', { ...source, ...bandInput, fold, harmonic }, controller.signal)
      .then((data) => { setBand(data); setError(null); })
      .catch((err) => { if (!controller.signal.aborted) { setBand(null); setError(err.message); } });
    return () => controller.abort();
  }, [bandInput, fold, harmonic]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleExcluded(index) {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index); else next.add(index);
      return next;
    });
  }

  const traces = [];
  if (active) {
    const marker = (points, color, name, symbol = 'x') => ({
      type: 'scatter', mode: 'markers', name, x: points.map((p) => p.x), y: points.map((p) => p.y),
      marker: { color, size: 8, symbol }, showlegend: false, hoverinfo: 'skip',
    });
    // Always present while active: adding the first overlay trace would
    // otherwise reflow the plot and shift the user's next click.
    const closed = polygon.length > 2 ? [...polygon, polygon[0]] : polygon;
    traces.push({ ...marker(closed, COLORS.region, 'Region', 'circle'), mode: 'lines+markers', line: { color: COLORS.region, width: 1.5, dash: 'dot' } });
    if (backbone) {
      const kept = backbone.time_utc.map((x, i) => ({ x, y: backbone.freq_mhz[i] })).filter((_, i) => !excluded.has(i));
      traces.push({ ...marker(kept, COLORS.points, 'Maxima', 'circle'), marker: { color: COLORS.points, size: 3 } });
    }
    if (shock) {
      traces.push({ type: 'scatter', mode: 'lines', x: shock.curve.time_utc, y: shock.curve.fit_freq_mhz, line: { color: COLORS.fit, width: 2 }, showlegend: false, hoverinfo: 'skip' });
    }
    if (upper.length) traces.push(marker(upper, COLORS.upper, 'Upper lane'));
    if (lower.length) traces.push(marker(lower, COLORS.lower, 'Lower lane'));
    if (band) {
      [[band.upper_fit, COLORS.upper], [band.lower_fit, COLORS.lower]].forEach(([fit, color]) => traces.push({
        type: 'scatter', mode: 'lines', x: fit.curve_time_utc, y: fit.curve_freq_mhz, line: { color, width: 1.5 }, showlegend: false, hoverinfo: 'skip',
      }));
    }
  }

  return {
    source, pickMode, setPickMode, polygon, setPolygon, backbone, excluded, toggleExcluded,
    fold, setFold, harmonic, setHarmonic, shock, upper, setUpper, lower, setLower,
    band, setBandInput, setBand, error, busy, analyzeRegion, onPlotClick, traces,
    calculateBands: () => setBandInput({ upper: asPairs(upper), lower: asPairs(lower) }),
  };
}
