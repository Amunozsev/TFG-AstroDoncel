import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import Plotly from './plotly';
import _factory from 'react-plotly.js/factory';
import { apiFetch } from './api';

const Plot = (_factory.default ?? _factory)(Plotly);

// ── Solar geometry (subsolar point + terminator) ────────────────────────────
// Approximate NOAA solar-position formulas; precision is well within what a
// day/night overlay on a world map needs.
function subsolarPoint(date) {
  const start = Date.UTC(date.getUTCFullYear(), 0, 0);
  const dayOfYear = Math.floor((date - start) / 86400000);
  const hours =
    date.getUTCHours() + date.getUTCMinutes() / 60 + date.getUTCSeconds() / 3600;
  const gamma = ((2 * Math.PI) / 365) * (dayOfYear - 1 + (hours - 12) / 24);
  const decl =
    0.006918 -
    0.399912 * Math.cos(gamma) +
    0.070257 * Math.sin(gamma) -
    0.006758 * Math.cos(2 * gamma) +
    0.000907 * Math.sin(2 * gamma) -
    0.002697 * Math.cos(3 * gamma) +
    0.00148 * Math.sin(3 * gamma); // radians
  const eqtime =
    229.18 *
    (0.000075 +
      0.001868 * Math.cos(gamma) -
      0.032077 * Math.sin(gamma) -
      0.014615 * Math.cos(2 * gamma) -
      0.040849 * Math.sin(2 * gamma)); // minutes
  const lat = (decl * 180) / Math.PI;
  let lon = -15 * (hours - 12 + eqtime / 60);
  lon = ((lon + 540) % 360) - 180;
  return { lat, lon };
}

// Terminator = the locus of points 90° of arc from the subsolar point.
// Returns lat/lon arrays with nulls inserted where the curve wraps the
// antimeridian, so the flat-map line does not draw a horizontal streak.
function terminatorCurve(sub) {
  const lat0 = (sub.lat * Math.PI) / 180;
  const lon0 = (sub.lon * Math.PI) / 180;
  const lats = [];
  const lons = [];
  let prevLon = null;
  for (let t = 0; t <= 360; t += 2) {
    const theta = (t * Math.PI) / 180;
    const lat = Math.asin(Math.cos(lat0) * Math.cos(theta));
    const lon =
      lon0 + Math.atan2(Math.sin(theta) * Math.cos(lat0), -Math.sin(lat0) * Math.sin(lat));
    let lonDeg = ((lon * 180) / Math.PI + 540) % 360 - 180;
    if (prevLon !== null && Math.abs(lonDeg - prevLon) > 180) {
      lats.push(null);
      lons.push(null);
    }
    lats.push((lat * 180) / Math.PI);
    lons.push(lonDeg);
    prevLon = lonDeg;
  }
  return { lats, lons };
}

// A "cap" = the set of points at a fixed angular radius from a centre, i.e. a
// circle on the sphere. Used to build the day glow (around the subsolar point)
// and the graduated night shadow (around the antisolar point).
function capPolygon(cLat, cLon, radiusDeg, n = 96) {
  const cLatR = (cLat * Math.PI) / 180;
  const cLonR = (cLon * Math.PI) / 180;
  const r = (radiusDeg * Math.PI) / 180;
  const lats = [];
  const lons = [];
  for (let i = 0; i <= n; i++) {
    const theta = (i / n) * 2 * Math.PI;
    const lat = Math.asin(
      Math.sin(cLatR) * Math.cos(r) + Math.cos(cLatR) * Math.sin(r) * Math.cos(theta),
    );
    const lon =
      cLonR +
      Math.atan2(
        Math.sin(theta) * Math.sin(r) * Math.cos(cLatR),
        Math.cos(r) - Math.sin(cLatR) * Math.sin(lat),
      );
    lats.push((lat * 180) / Math.PI);
    lons.push((((lon * 180) / Math.PI + 540) % 360) - 180);
  }
  return { lats, lons };
}

// Day/night shading built on the real solar-elevation zones, not a smooth
// gradient. A point's angular distance from the subsolar point equals the solar
// zenith angle z, so:
//   z < 90°  → day       (a warm wash over the lit hemisphere)
//   90–99°   → dusk/dawn band 1  (civil + nautical twilight)
//   99–108°  → dusk/dawn band 2  (astronomical twilight)
//   z > 108° → deep night (uniformly dark)
// Distance-from-antisolar a = 180 − z, so the night caps use radii 90/81/72.
function dayNightTraces(sub) {
  const antiLat = -sub.lat;
  const antiLon = (((sub.lon + 180) + 540) % 360) - 180;
  const traces = [];

  const cap = (cLat, cLon, radius, color) => {
    const p = capPolygon(cLat, cLon, radius);
    return {
      type: 'scattergeo',
      mode: 'lines',
      lon: p.lons,
      lat: p.lats,
      fill: 'toself',
      fillcolor: color,
      line: { width: 0, color: 'rgba(0,0,0,0)' },
      hoverinfo: 'skip',
      showlegend: false,
    };
  };

  // Day: one gentle warm wash over the lit hemisphere.
  traces.push(cap(sub.lat, sub.lon, 90, 'rgba(255, 246, 214, 0.05)'));

  // Darkening bands stacked around the antisolar point; overlap deepens toward
  // the dark side. Radii beyond 90° reach onto the DAY side of the terminator,
  // dimming the low-sun dawn/dusk zone there too, so the transition is realistic
  // and symmetric instead of a hard edge:
  //   z<72 bright day │ 72–90 two dim day bands │ 90–108 two twilight bands │ >108 deep night
  const nightColor = 'rgba(4, 9, 20, 0.16)';
  [108, 99, 90, 81, 72].forEach((rad) => traces.push(cap(antiLat, antiLon, rad, nightColor)));

  return traces;
}

const INITIAL_ROT_LON = -20;

const GEO_BASE = {
  showland: true,
  landcolor: '#16324f',
  showocean: true,
  oceancolor: '#0a1826',
  showcountries: true,
  countrycolor: '#24425f',
  coastlinecolor: '#2c516f',
  coastlinewidth: 0.6,
  showlakes: false,
  showframe: false,
  bgcolor: 'rgba(0,0,0,0)',
  framecolor: 'rgba(0,0,0,0)',
};

export default function StationsMap({ onOpenStation }) {
  const [data, setData]         = useState(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [projection, setProjection] = useState('orthographic'); // 'orthographic' | 'natural earth'
  const [autoRotate, setAutoRotate] = useState(true);
  const [showSun, setShowSun]   = useState(true);
  const [filter, setFilter]     = useState('');
  const [statusFilter, setStatusFilter] = useState('all'); // 'all' | 'operative' | 'offline'
  const [now, setNow]           = useState(() => new Date());
  const [updatedAt, setUpdatedAt] = useState(null); // last successful stations fetch

  const gdRef = useRef(null);              // Plotly graph div, for smooth relayout
  const rotLon = useRef(INITIAL_ROT_LON);  // current globe longitude rotation
  const lastInteract = useRef(0);          // ts of last user drag/zoom, pauses auto-rotate
  const listenersBound = useRef(false);

  const isGlobe = projection === 'orthographic';

  // ── Load station geo data ──────────────────────────────────────────────────
  // `silent` = background refresh: don't blank the map with the loading overlay
  // and keep the previous data if the request fails.
  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const res = await apiFetch('/api/stations/geo');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setUpdatedAt(new Date());
    } catch (err) {
      if (!silent) setError(err.message);
      else console.warn('Silent stations refresh failed:', err.message);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => { queueMicrotask(() => load()); }, [load]);

  // Refresh the solar position every minute so the terminator stays live.
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  // Re-check operative status every few minutes in the background. Station data
  // has daily granularity on ETHZ, so a slow cadence is plenty.
  useEffect(() => {
    const id = setInterval(() => load(true), 5 * 60_000);
    return () => clearInterval(id);
  }, [load]);

  // ── Auto-rotate the globe via relayout (smooth, no React re-render) ─────────
  // Reads the live rotation each tick so it resumes seamlessly from wherever the
  // user last dragged, and pauses while the user is actively interacting.
  useEffect(() => {
    if (!isGlobe || !autoRotate) return;
    const id = setInterval(() => {
      const gd = gdRef.current;
      if (!gd) return;
      if (Date.now() - lastInteract.current < 1200) return; // user is dragging/zooming
      const live = gd?._fullLayout?.geo?.projection?.rotation?.lon;
      const base = typeof live === 'number' ? live : rotLon.current;
      rotLon.current = ((base + 0.5 + 540) % 360) - 180;
      Plotly.relayout(gd, { 'geo.projection.rotation.lon': rotLon.current });
    }, 50);
    return () => clearInterval(id);
  }, [isGlobe, autoRotate]);

  const sub = useMemo(() => subsolarPoint(now), [now]);

  // ── Build Plotly traces ─────────────────────────────────────────────────────
  const traces = useMemo(() => {
    if (!data) return [];
    const q = filter.trim().toUpperCase();
    const match = (s) => !q || s.station.toUpperCase().includes(q);

    const mkTrace = (stations, color, name) => ({
      type: 'scattergeo',
      mode: 'markers',
      name,
      lon: stations.map((s) => s.lon),
      lat: stations.map((s) => s.lat),
      customdata: stations.map((s) => [
        s.station,
        s.burst_count,
        s.coord_source === 'fits' ? '' : '<br><i>≈ approx. location</i>',
      ]),
      hovertemplate:
        '<b>%{customdata[0]}</b><br>' +
        `${name}<br>` +
        '☀ %{customdata[1]} bursts this month<br>' +
        '%{lat:.2f}°, %{lon:.2f}°%{customdata[2]}<br>' +
        '<span style="font-size:11px">click to open spectrograms</span>' +
        '<extra></extra>',
      marker: {
        size: stations.map((s) => (q && match(s) ? 13 : 9)),
        color,
        opacity: stations.map((s) => (q ? (match(s) ? 1 : 0.15) : 0.95)),
        line: { width: 1.2, color: '#0a1826' },
      },
    });

    // Day/night shading sits underneath everything else.
    const out = showSun ? dayNightTraces(sub) : [];

    const visible = data.stations.filter((s) =>
      statusFilter === 'operative' ? s.operative
        : statusFilter === 'offline' ? !s.operative
        : true,
    );
    const op = visible.filter((s) => s.operative);
    const nonop = visible.filter((s) => !s.operative);

    out.push(
      mkTrace(nonop, '#ef4444', 'Non-operative'),
      mkTrace(op, '#22c55e', 'Operative'),
    );

    if (showSun) {
      const term = terminatorCurve(sub);
      out.push({
        type: 'scattergeo',
        mode: 'lines',
        name: 'Terminator',
        lon: term.lons,
        lat: term.lats,
        line: { width: 1.4, color: 'rgba(250, 204, 21, 0.55)', dash: 'dot' },
        hoverinfo: 'skip',
        showlegend: false,
        connectgaps: false,
      });
      out.push({
        type: 'scattergeo',
        mode: 'markers',
        name: 'Sun',
        lon: [sub.lon],
        lat: [sub.lat],
        hovertemplate: 'Subsolar point<br>%{lat:.1f}°, %{lon:.1f}°<extra></extra>',
        marker: {
          size: 22,
          color: 'rgba(250, 204, 21, 0.9)',
          line: { width: 0 },
          symbol: 'circle',
        },
        showlegend: false,
      });
    }

    return out;
  }, [data, filter, statusFilter, showSun, sub]);

  const layout = useMemo(
    () => ({
      autosize: true,
      margin: { l: 0, r: 0, t: 0, b: 0 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      showlegend: true,
      legend: {
        x: 0.01, y: 0.99,
        bgcolor: 'rgba(13,27,42,0.75)',
        bordercolor: '#1a2f46',
        borderwidth: 1,
        font: { color: '#c8d6e5', size: 12 },
      },
      geo: {
        ...GEO_BASE,
        projection: isGlobe
          ? { type: 'orthographic', rotation: { lon: INITIAL_ROT_LON, lat: 18, roll: 0 } }
          : { type: 'natural earth' },
      },
    }),
    [isGlobe],
  );

  // scrollZoom enables the wheel to zoom the map; drag pans (flat) or rotates
  // the globe (orthographic) natively.
  const config = useMemo(
    () => ({ displayModeBar: false, responsive: true, scrollZoom: true }),
    [],
  );

  function handleClick(ev) {
    const pt = ev?.points?.[0];
    const station = Array.isArray(pt?.customdata) ? pt.customdata[0] : pt?.customdata;
    if (station && onOpenStation) onOpenStation(station);
  }

  // Bind native listeners once so we can pause auto-rotate while the user drags
  // or zooms, and resume smoothly afterwards.
  function bindInteractionListeners(gd) {
    gdRef.current = gd;
    if (listenersBound.current || !gd) return;
    listenersBound.current = true;
    const bump = () => { lastInteract.current = Date.now(); };
    gd.addEventListener('pointerdown', bump);
    gd.addEventListener('wheel', bump, { passive: true });
    gd.addEventListener('pointermove', (e) => { if (e.buttons) bump(); });
  }

  const opCount = data?.operative_count ?? 0;
  const total = data?.total_count ?? 0;

  return (
    <div className="stations-map">
      <div className="map-toolbar">
        <div className="map-title-block">
          <h2>Stations Map</h2>
          <p className="map-subtitle">
            <span className="dot dot-green" /> operative&nbsp;·&nbsp;
            <span className="dot dot-red" /> non-operative — click a station to open its spectrograms
          </p>
        </div>

        <div className="map-controls">
          <div className="segmented map-seg">
            <button
              className={isGlobe ? 'active' : ''}
              onClick={() => setProjection('orthographic')}
            >
              🌐 Globe
            </button>
            <button
              className={!isGlobe ? 'active' : ''}
              onClick={() => setProjection('natural earth')}
            >
              🗺 Map
            </button>
          </div>

          <div className="segmented map-seg" title="Filter by operative status">
            <button
              className={statusFilter === 'all' ? 'active' : ''}
              onClick={() => setStatusFilter('all')}
            >
              All
            </button>
            <button
              className={statusFilter === 'operative' ? 'active' : ''}
              onClick={() => setStatusFilter('operative')}
            >
              🟢 Operative
            </button>
            <button
              className={statusFilter === 'offline' ? 'active' : ''}
              onClick={() => setStatusFilter('offline')}
            >
              🔴 Offline
            </button>
          </div>

          <label className="map-check" title="Spin the globe automatically">
            <input
              type="checkbox"
              checked={autoRotate}
              disabled={!isGlobe}
              onChange={(e) => setAutoRotate(e.target.checked)}
            />
            Auto-rotate
          </label>

          <label className="map-check" title="Show the day/night terminator and subsolar point">
            <input
              type="checkbox"
              checked={showSun}
              onChange={(e) => setShowSun(e.target.checked)}
            />
            ☀ Day/night
          </label>

          <input
            type="text"
            className="map-search"
            placeholder="Find station…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />

          <button className="map-refresh" onClick={load} title="Re-check operative status">
            ⟳
          </button>
        </div>
      </div>

      <div className="map-canvas">
        {loading && <div className="map-overlay">Loading stations…</div>}
        {error && (
          <div className="map-overlay map-error">
            Could not load stations: {error}
            <button className="map-refresh" onClick={load} style={{ marginLeft: '0.6rem' }}>
              Retry
            </button>
          </div>
        )}
        {!loading && !error && data && (
          <Plot
            data={traces}
            layout={layout}
            config={config}
            style={{ width: '100%', height: '100%' }}
            useResizeHandler
            onClick={handleClick}
            onInitialized={(fig, gd) => bindInteractionListeners(gd)}
            onUpdate={(fig, gd) => bindInteractionListeners(gd)}
          />
        )}
      </div>

      {data && (
        <div className="map-statusbar">
          <span className="map-stat">
            <span className="dot dot-green" /> {opCount} operative
          </span>
          <span className="map-stat">
            <span className="dot dot-red" /> {total - opCount} offline
          </span>
          <span className="map-stat" title="Coordinates read from the stations' own FITS headers">
            📍 {total} mapped{typeof data.fits_coord_count === 'number' ? ` (${data.fits_coord_count} from data)` : ''}
          </span>
          {data.unmapped?.length > 0 && (
            <span className="map-stat map-stat-warn" title={data.unmapped.join(', ')}>
              ⏳ {data.unmapped.length} locating…
            </span>
          )}
          {data.burst_month && (
            <span className="map-stat">
              ☀ {data.burst_total} bursts in {data.burst_month}
            </span>
          )}
          {data.reference_date ? (
            <span className="map-stat map-stat-muted">
              status as of {data.reference_date} (ETHZ)
            </span>
          ) : (
            <span className="map-stat map-stat-warn">
              ⚠ ETHZ unreachable — status may be stale
            </span>
          )}
          {updatedAt && (
            <span className="map-stat map-stat-muted" title="Auto-refreshes every 5 min">
              updated {updatedAt.toLocaleTimeString()}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
