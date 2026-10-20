import { useCallback, useEffect, useRef } from 'react';
import { Plot } from './plotly';
import { TYPE_II_COLORS as COLORS, asPairs } from './useTypeII';

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function Value({ value, error, digits = 2 }) {
  if (value === undefined || value === null || !Number.isFinite(value)) return '—';
  return error !== undefined && Number.isFinite(error) ? `${value.toFixed(digits)} ± ${error.toFixed(digits)}` : value.toFixed(digits);
}

function exportShockCsv(t2) {
  const { backbone, excluded, shock, source } = t2;
  const rows = [['UTC', 'time_s', 'observed_freq_mhz', 'used_in_fit']];
  backbone.time_utc.forEach((time, i) => rows.push([time, backbone.time_s[i], backbone.freq_mhz[i], !excluded.has(i)]));
  rows.push([], ['UTC', 'time_s', 'fit_freq_mhz', 'height_rsun', 'shock_speed_km_s']);
  shock.curve.time_s.forEach((time, i) => rows.push([
    shock.curve.time_utc[i], time, shock.curve.fit_freq_mhz[i], shock.curve.height_rsun[i], shock.curve.speed_km_s[i],
  ]));
  download(`type-ii-${source.station}-${source.date}.csv`, rows.map((row) => row.join(',')).join('\r\n'), 'text/csv;charset=utf-8');
}

function exportJson(t2) {
  const { source, polygon, shock, band, upper, lower } = t2;
  const report = {
    schema: 'astrodoncel.type-ii.v1',
    source,
    method: {
      time_origin: 'seconds since the FITS observation start',
      fit: 'least squares f = a * t^-b',
      density_model: `Newkirk (1961) x ${shock?.fold ?? band?.fold} fold`,
      emission: shock?.harmonic || band?.harmonic ? 'harmonic (frequencies and drift halved)' : 'fundamental',
      band_splitting: 'experimental: Vrsnak et al. (2002) perpendicular low-beta shock, upstream (lower lane) density',
    },
    region: polygon.map((p) => [p.x, p.y]),
    shock,
    band_splitting: band ? { upper_points: asPairs(upper), lower_points: asPairs(lower), ...band } : null,
  };
  download(`type-ii-${source.station}-${source.date}.json`, `${JSON.stringify(report, null, 2)}\n`, 'application/json');
}

const PICK_LABELS = { region: 'drawing the burst region', upper: 'marking the upper lane', lower: 'marking the lower lane' };

/** Spectrogram header chip: the drawing controls stay next to the plot being clicked. */
export function TypeIIStatus({ t2 }) {
  if (!t2.pickMode) return null;
  const count = { region: t2.polygon, upper: t2.upper, lower: t2.lower }[t2.pickMode].length;
  return (
    <span className="header-status ruler type-ii-status">
      Type II: {PICK_LABELS[t2.pickMode]} · {count} pts
      {t2.pickMode === 'region'
        ? <button type="button" disabled={count < 3 || t2.busy} onClick={t2.analyzeRegion}>Extract maxima</button>
        : <button type="button" onClick={() => t2.setPickMode(null)}>Done</button>}
    </span>
  );
}

export function TypeIIResult({ t2, theme = 'dark', onClose }) {
  const plotTheme = theme === 'light'
    ? { surface: '#f7f9fc', text: '#3f5870', grid: '#d8e1ea' }
    : { surface: '#080d12', text: '#c8d9e8', grid: '#1e3448' };
  const plotLayout = (xTitle, yTitle, xType = 'date') => ({
    autosize: true, height: 260, margin: { l: 64, r: 24, t: 14, b: 50 },
    paper_bgcolor: plotTheme.surface, plot_bgcolor: plotTheme.surface, font: { color: plotTheme.text },
    xaxis: { title: xTitle, type: xType, gridcolor: plotTheme.grid },
    yaxis: { title: yTitle, gridcolor: plotTheme.grid },
    showlegend: false, hovermode: 'closest',
  });
  // Bind the click on the graph div itself; react-plotly's onClick prop loses
  // its listener after figure updates (same workaround as the spectrogram).
  const clickRef = useRef(null);
  useEffect(() => { clickRef.current = (ev) => {
    const point = ev?.points?.[0];
    if (point?.curveNumber === 0) t2.toggleExcluded(point.pointIndex);
  }; });
  const onClick = useCallback((ev) => clickRef.current?.(ev), []);
  const bind = useCallback((_figure, gd) => {
    gd.removeListener?.('plotly_click', onClick);
    gd.on?.('plotly_click', onClick);
  }, [onClick]);

  const { backbone, excluded, shock, band, pickMode } = t2;
  const s = shock?.summary;
  const pick = (mode) => {
    const starting = pickMode !== mode;
    t2.setPickMode(starting ? mode : null);
    // The clicks happen on the spectrogram above this panel.
    if (starting) document.querySelector('.main-header')?.closest('main')?.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <section className="lightcurve-result type-ii-result" aria-label="Type II burst analysis">
      <header>
        <div>
          <span className="section-kicker">Shock kinematics</span>
          <h2>Type II analysis</h2>
          <p>{t2.source?.station} · {t2.source?.filename} · heights from the Newkirk model are estimates</p>
        </div>
        <div className="lightcurve-actions">
          <button type="button" disabled={!shock} onClick={() => exportShockCsv(t2)}>Export CSV</button>
          <button type="button" disabled={!shock && !band} onClick={() => exportJson(t2)}>Export JSON</button>
          <button type="button" className="lightcurve-close" onClick={onClose}>Close analysis</button>
        </div>
      </header>

      <div className="type-ii-controls">
        <button type="button" className={`btn-tool${pickMode === 'region' ? ' active' : ''}`} onClick={() => pick('region')}>
          {pickMode === 'region' ? `Drawing region · ${t2.polygon.length} pts` : 'Draw burst region'}
        </button>
        <button type="button" className="btn-tool" disabled={t2.polygon.length < 3 || t2.busy} onClick={t2.analyzeRegion}>
          {t2.busy ? 'Extracting…' : 'Extract maxima'}
        </button>
        <button type="button" className="btn-tool" disabled={!t2.polygon.length} onClick={() => t2.setPolygon([])}>Clear region</button>
        <label className="type-ii-field">Newkirk fold
          <select className="control-input" value={t2.fold} onChange={(e) => t2.setFold(Number(e.target.value))}>
            {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <label className="type-ii-field type-ii-check">
          <input type="checkbox" checked={t2.harmonic} onChange={(e) => t2.setHarmonic(e.target.checked)} /> Harmonic emission
        </label>
      </div>
      <p className="tool-help">
        Click around the burst on the spectrogram to draw the region, then extract the maximum-intensity frequency of
        each instant. Click a point in the chart below to exclude or restore it as an outlier.
      </p>
      {t2.error && <p className="page-error" role="alert">{t2.error}</p>}

      {backbone && (
        <div className="type-ii-grid">
          <Plot
            data={[
              {
                type: 'scatter', mode: 'markers', x: backbone.time_utc, y: backbone.freq_mhz,
                marker: { size: 5, color: backbone.time_utc.map((_, i) => (excluded.has(i) ? COLORS.excluded : COLORS.points)) },
                hovertemplate: '%{x}<br>%{y:.2f} MHz<extra>click to exclude/restore</extra>',
              },
              ...(shock ? [{ type: 'scatter', mode: 'lines', x: shock.curve.time_utc, y: shock.curve.fit_freq_mhz, line: { color: COLORS.fit, width: 2 }, hoverinfo: 'skip' }] : []),
            ]}
            layout={plotLayout('Time (UTC)', 'Frequency (MHz)')}
            config={{ responsive: true, displaylogo: false }}
            onInitialized={bind}
            onUpdate={bind}
            useResizeHandler
            style={{ width: '100%' }}
          />
          {s && (
            <table className="type-ii-table">
              <tbody>
                <tr><th>Fit</th><td>f = {shock.fit.a.toFixed(2)} · t<sup>−{shock.fit.b.toFixed(3)}</sup> · R² {shock.fit.r2.toFixed(3)} · RMSE {shock.fit.rmse.toFixed(2)} MHz · {shock.fit.points} pts</td></tr>
                <tr><th>Start frequency</th><td><Value value={s.start_freq_mhz} error={s.start_freq_err_mhz} /> MHz{shock.harmonic ? ' (fundamental)' : ''}</td></tr>
                <tr><th>Start drift</th><td><Value value={s.start_drift_mhz_s} error={s.start_drift_err_mhz_s} digits={3} /> MHz/s</td></tr>
                <tr><th>Mean drift</th><td><Value value={s.mean_drift_mhz_s} error={s.std_drift_mhz_s} digits={3} /> MHz/s (± spread)</td></tr>
                <tr><th>Start shock height</th><td><Value value={s.start_height_rsun} error={s.start_height_err_rsun} digits={3} /> R☉</td></tr>
                <tr><th>Mean shock height</th><td><Value value={s.mean_height_rsun} error={s.std_height_rsun} digits={3} /> R☉ (± spread)</td></tr>
                <tr><th>Start shock speed</th><td><Value value={s.start_speed_km_s} error={s.start_speed_err_km_s} digits={0} /> km/s</td></tr>
                <tr><th>Mean shock speed</th><td><Value value={s.mean_speed_km_s} error={s.std_speed_km_s} digits={0} /> km/s (± spread)</td></tr>
              </tbody>
            </table>
          )}
        </div>
      )}

      <div className="type-ii-band">
        <h3>Band-splitting <span className="badge-experimental">experimental</span></h3>
        <p className="tool-help">
          Mark several points on the upper lane and on the lower lane of a split type II. The lower (upstream) lane gives
          the shock speed and the density used for the magnetic field.
        </p>
        <div className="type-ii-controls">
          <button type="button" className={`btn-tool${pickMode === 'upper' ? ' active' : ''}`} onClick={() => pick('upper')}>Upper lane · {t2.upper.length}</button>
          <button type="button" className={`btn-tool${pickMode === 'lower' ? ' active' : ''}`} onClick={() => pick('lower')}>Lower lane · {t2.lower.length}</button>
          <button type="button" className="btn-tool" disabled={t2.upper.length < 3 || t2.lower.length < 3} onClick={t2.calculateBands}>Calculate</button>
          <button type="button" className="btn-tool" disabled={!t2.upper.length && !t2.lower.length} onClick={() => { t2.setUpper([]); t2.setLower([]); t2.setBandInput(null); t2.setBand(null); }}>Clear lanes</button>
        </div>
        {band && (
          <div className="type-ii-grid">
            <Plot
              data={[{ type: 'scatter', mode: 'lines+markers', x: band.profile.height_rsun, y: band.profile.magnetic_field_g, line: { color: COLORS.upper }, marker: { size: 4 } }]}
              layout={{ ...plotLayout('Height (R☉)', 'B (G)', 'linear'), yaxis: { title: 'B (G)', type: 'log', gridcolor: plotTheme.grid } }}
              config={{ responsive: true, displaylogo: false }}
              useResizeHandler
              style={{ width: '100%' }}
            />
            <table className="type-ii-table">
              <tbody>
                {[
                  ['Relative bandwidth', band.summary.relative_bandwidth, 3, ''],
                  ['Compression ratio X', band.summary.compression_ratio, 3, ''],
                  ['Alfvén Mach number', band.summary.alfven_mach, 2, ''],
                  ['Shock speed', band.summary.shock_speed_km_s, 0, 'km/s'],
                  ['Alfvén speed', band.summary.alfven_speed_km_s, 0, 'km/s'],
                  ['Magnetic field', band.summary.magnetic_field_g, 3, 'G'],
                  ['Height', band.summary.height_rsun, 3, 'R☉'],
                ].map(([label, stat, digits, unit]) => (
                  <tr key={label}><th>{label}</th><td><Value value={stat.mean} error={stat.std} digits={digits} /> {unit} (mean ± spread)</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
