import { useState, useEffect, useCallback } from 'react';
import Spectrogram from './Spectrogram';
import './App.css';

const API_BASE = 'http://localhost:8000';

const FALLBACK_STATIONS = [
  'ALASKA-HAARP', 'AUSTRIA-UNIGRAZ', 'BIR', 'HUMAIN', 'LEARMONTH',
  'MAURITIUS', 'PERU-ICA', 'PHOENIX', 'SPAIN-PERALEJOS', 'SPAIN-SIGUENZA',
  'SSRT', 'SWISS-LANDSCHLACHT',
];

const TABS = [
  { id: 'processing', label: 'Processing' },
  { id: 'display',    label: 'Display' },
  { id: 'context',    label: 'Solar context' },
  { id: 'layers',     label: 'Layers' },
  { id: 'tools',      label: 'Tools' },
];

export default function App() {
  const [stations, setStations]             = useState(FALLBACK_STATIONS);
  const [stationsSource, setStationsSource] = useState('');
  const [stationFilter, setStationFilter]   = useState('');
  // Primary station: drives the burst-file list and the 15-min sync block.
  // No station is preselected on startup — the user must pick one.
  const [station, setStation]               = useState(null);
  // All stations selected for multi-layer loading
  const [selectedStations, setSelectedStations] = useState([]);
  const [date, setDate]                     = useState(() => new Date().toISOString().slice(0, 10));

  // Daily burst list (primary station only)
  const [files, setFiles]                   = useState([]);
  const [filesLoading, setFilesLoading]     = useState(false);
  const [selectedFile, setSelectedFile]     = useState(null);
  const [collapsedHours, setCollapsedHours] = useState({});

  const [useSahanFilter, setSahan]          = useState(false);
  const [rfiParams, setRfiParams]           = useState({
    zThresh: 6.0, occupancy: 0.15, minComponent: 9, impulsive: true,
  });
  const [showGoes, setShowGoes]             = useState(false);
  const [colormap, setColormap]             = useState('observatory');
  const [zmin, setZmin]                     = useState(-5);
  const [zmax, setZmax]                     = useState(30);
  const [useCustomZ, setUseCustomZ]         = useState(false);
  const [compareMode, setCompareMode]       = useState('panels'); // 'panels' | 'overlay'
  const [autoContrastZoom, setAutoContrastZoom] = useState(false);
  const [triggerLoad, setTriggerLoad]       = useState(0);
  const [hasLoaded, setHasLoaded]           = useState(false);

  // Fetched layer data (owned here, passed down to Spectrogram)
  const [layers, setLayers]                 = useState([]);
  const [failedStations, setFailedStations] = useState([]);
  const [fetchLoading, setFetchLoading]     = useState(false);
  const [fetchError, setFetchError]         = useState(null);

  // Per-layer UI state: { [station]: { visible: bool, opacity: number } }
  const [layerState, setLayerState]         = useState({});

  // Toolbar tabs / tools
  const [activeTab, setActiveTab]           = useState(null);
  const [rulerMode, setRulerMode]           = useState(false);
  const [showHeaderViewer, setShowHeaderViewer] = useState(false);
  const [headerLayerIdx, setHeaderLayerIdx] = useState(0);

  // ── Load station list ─────────────────────────────────────────────────────
  useEffect(() => {
    async function loadStations() {
      try {
        const res = await fetch(`${API_BASE}/api/stations`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.stations?.length > 0) {
          setStations(data.stations);
          setStationsSource(data.source);
          if (station && !data.stations.includes(station)) {
            setStation(null);
            setSelectedStations([]);
          }
        }
      } catch (err) {
        console.warn('Station list from API failed, using fallback:', err.message);
        setStationsSource('static');
      }
    }
    loadStations();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Reload burst list when primary station or date changes ────────────────
  const loadFiles = useCallback(async (st, dt) => {
    setFiles([]);
    setSelectedFile(null);
    setCollapsedHours({});
    if (!st) return;
    setFilesLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/files?station=${encodeURIComponent(st)}&date=${encodeURIComponent(dt)}`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setFiles(data.files ?? []);
      if (data.files?.length > 0) {
        setSelectedFile(data.files[0].filename);
      }
    } catch (err) {
      console.warn('Could not load burst list:', err.message);
    } finally {
      setFilesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFiles(station, date);
  }, [station, date, loadFiles]);

  // ── Fetch spectrogram layers on explicit Load ─────────────────────────────
  useEffect(() => {
    if (!hasLoaded || triggerLoad === 0) return;
    if (selectedStations.length === 0) return;

    async function fetchLayers() {
      setFetchLoading(true);
      setFetchError(null);
      try {
        let newLayers;
        let newFailed = [];

        const rfiQS = {
          rfi_z_thresh: String(rfiParams.zThresh),
          rfi_occupancy: String(rfiParams.occupancy),
          rfi_min_component: String(rfiParams.minComponent),
          rfi_impulsive: String(rfiParams.impulsive),
        };

        if (selectedStations.length > 1) {
          const params = new URLSearchParams({
            date,
            sahan_filter: String(useSahanFilter),
            max_time_bins: '1500',
            ...rfiQS,
          });
          if (selectedFile) params.set('filename', selectedFile);
          // Primary station first so the backend anchors the 15-min block to it
          const ordered = [station, ...selectedStations.filter((s) => s !== station)]
            .filter(Boolean);
          ordered.forEach((s) => params.append('stations', s));
          const res = await fetch(`${API_BASE}/api/spectrogram/combine?${params}`);
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail ?? `Error ${res.status}`);
          }
          const data = await res.json();
          newLayers = data.layers;
          newFailed = data.failed ?? [];
        } else {
          const params = new URLSearchParams({
            station: selectedStations[0],
            date,
            sahan_filter: String(useSahanFilter),
            max_time_bins: '1500',
            ...rfiQS,
          });
          if (selectedFile) params.set('filename', selectedFile);
          const res = await fetch(`${API_BASE}/api/spectrogram?${params}`);
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail ?? `Error ${res.status}`);
          }
          newLayers = [await res.json()];
        }

        setLayers(newLayers);
        setFailedStations(newFailed);

        // Preserve existing state for stations already loaded; initialise new ones
        setLayerState((prev) => {
          const next = {};
          for (const layer of newLayers) {
            next[layer.station] = prev[layer.station] ?? { visible: true, opacity: 1 };
          }
          return next;
        });

        // Seed contrast sliders from first layer if not in manual mode
        if (newLayers.length > 0 && !useCustomZ) {
          setZmin(Math.round(newLayers[0].vmin * 10) / 10);
          setZmax(Math.round(newLayers[0].vmax * 10) / 10);
        }
      } catch (err) {
        setFetchError(err.message);
        setLayers([]);
        setFailedStations([]);
      } finally {
        setFetchLoading(false);
      }
    }

    fetchLayers();
  }, [triggerLoad]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleLoad() {
    setHasLoaded(true);
    setTriggerLoad((n) => n + 1);
  }

  function handleChipClick(filename) {
    setSelectedFile(filename);
    setHasLoaded(true);
    setTriggerLoad((n) => n + 1);
  }

  // ── Keyboard navigation: ←/→ steps through the burst list ─────────────────
  useEffect(() => {
    function onKey(e) {
      if (files.length === 0) return;
      const tag = e.target?.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      const idx = files.findIndex((f) => f.filename === selectedFile);
      const next = e.key === 'ArrowRight'
        ? Math.min(files.length - 1, idx + 1)
        : Math.max(0, idx - 1);
      if (next !== idx && files[next]) handleChipClick(files[next].filename);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [files, selectedFile]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleStation(s) {
    if (selectedStations.includes(s)) {
      const next = selectedStations.filter((x) => x !== s);
      setSelectedStations(next);
      if (station === s) setStation(next[0] ?? null); // keep primary valid after removal
    } else {
      setSelectedStations([...selectedStations, s]);
      if (!station) setStation(s); // first pick becomes primary; later picks don't steal it
    }
  }

  function setLayerVisible(st, visible) {
    setLayerState((prev) => ({ ...prev, [st]: { ...prev[st], visible } }));
  }

  function setLayerOpacity(st, opacity) {
    setLayerState((prev) => ({ ...prev, [st]: { ...prev[st], opacity } }));
  }

  function setRfiParam(key, value) {
    setRfiParams((prev) => ({ ...prev, [key]: value }));
  }

  const loadDisabled =
    !date ||
    selectedStations.length === 0 ||
    (files.length > 0 && !selectedFile);

  const filteredStations = stationFilter
    ? stations.filter((s) => s.toUpperCase().includes(stationFilter.toUpperCase()))
    : stations;

  const rfiStats = layers[0]?.rfi_stats ?? null;

  // ── Tab panel contents ─────────────────────────────────────────────────────
  function renderTabPanel() {
    switch (activeTab) {
      case 'processing':
        return (
          <div className="tab-panel">
            <div className="tab-group">
              <label className="control-checkbox">
                <input
                  type="checkbox"
                  checked={useSahanFilter}
                  onChange={(e) => setSahan(e.target.checked)}
                />
                RFI filter v2 (Sahan)
              </label>
              <label className="control-checkbox" title="Connected-component stage; can also mask very bright bursts — disable if a burst disappears">
                <input
                  type="checkbox"
                  checked={rfiParams.impulsive}
                  disabled={!useSahanFilter}
                  onChange={(e) => setRfiParam('impulsive', e.target.checked)}
                />
                Impulsive stage
              </label>
            </div>
            <label className="tab-field">
              Z threshold
              <input
                type="number" className="control-input tab-num"
                min="0.5" max="20" step="0.5"
                value={rfiParams.zThresh}
                disabled={!useSahanFilter}
                onChange={(e) => setRfiParam('zThresh', parseFloat(e.target.value) || 6)}
              />
            </label>
            <label className="tab-field">
              Occupancy
              <input
                type="number" className="control-input tab-num"
                min="0.01" max="1" step="0.01"
                value={rfiParams.occupancy}
                disabled={!useSahanFilter}
                onChange={(e) => setRfiParam('occupancy', parseFloat(e.target.value) || 0.15)}
              />
            </label>
            <label className="tab-field">
              Min component
              <input
                type="number" className="control-input tab-num"
                min="1" max="500" step="1"
                value={rfiParams.minComponent}
                disabled={!useSahanFilter}
                onChange={(e) => setRfiParam('minComponent', parseInt(e.target.value, 10) || 9)}
              />
            </label>
            <div className="tab-group">
              <button
                className="btn-apply"
                onClick={handleLoad}
                disabled={loadDisabled}
                title="Re-run the pipeline with the current RFI parameters"
              >
                Apply
              </button>
              {rfiStats && rfiStats.persistent_channels !== undefined && (
                <span className="stat-chip" title="Stats from the last processed layer">
                  {rfiStats.persistent_channels} ch masked ·{' '}
                  {(rfiStats.masked_fraction * 100).toFixed(2)}% samples
                </span>
              )}
            </div>
          </div>
        );
      case 'display':
        return (
          <div className="tab-panel">
            <label className="tab-field">
              Colormap
              <select
                className="control-input"
                value={colormap}
                onChange={(e) => setColormap(e.target.value)}
              >
                <option value="observatory">Default</option>
                <option value="hot">Hot</option>
                <option value="inferno">Inferno</option>
                <option value="magma">Magma</option>
                <option value="plasma">Plasma</option>
                <option value="viridis">Viridis</option>
                <option value="cividis">Cividis</option>
                <option value="turbo">Turbo</option>
                <option value="jet">Jet</option>
                <option value="rdylbu">RdYlBu</option>
                <option value="cubehelix">Cubehelix</option>
                <option value="bone_r">Bone (inverted)</option>
              </select>
            </label>
            <label className="tab-field">
              Comparison mode
              <div className="segmented">
                <button
                  className={compareMode === 'panels' ? 'active' : ''}
                  onClick={() => setCompareMode('panels')}
                  title="One synchronised panel per station (recommended)"
                >
                  Panels
                </button>
                <button
                  className={compareMode === 'overlay' ? 'active' : ''}
                  onClick={() => setCompareMode('overlay')}
                  title="Translucent blend: upper layers fade out at low intensity"
                >
                  Overlay
                </button>
              </div>
            </label>
            <div className="tab-group">
              <label className="control-checkbox">
                <input
                  type="checkbox"
                  checked={useCustomZ}
                  onChange={(e) => setUseCustomZ(e.target.checked)}
                />
                Manual contrast
              </label>
              <label className="control-checkbox" title="Recompute vmin/vmax on the zoomed region instead of keeping the overview contrast">
                <input
                  type="checkbox"
                  checked={autoContrastZoom}
                  onChange={(e) => setAutoContrastZoom(e.target.checked)}
                />
                Auto-contrast on zoom
              </label>
            </div>
            <label className="tab-field slider-field">
              <span className="slider-row">
                <span>Z min</span>
                <span className="slider-value">{zmin}</span>
              </span>
              <input
                type="range" className="control-slider"
                min="-100" max="50" step="0.5"
                value={zmin}
                disabled={!useCustomZ}
                onChange={(e) => { setUseCustomZ(true); setZmin(parseFloat(e.target.value)); }}
              />
            </label>
            <label className="tab-field slider-field">
              <span className="slider-row">
                <span>Z max</span>
                <span className="slider-value">{zmax}</span>
              </span>
              <input
                type="range" className="control-slider"
                min="-50" max="300" step="0.5"
                value={zmax}
                disabled={!useCustomZ}
                onChange={(e) => { setUseCustomZ(true); setZmax(parseFloat(e.target.value)); }}
              />
            </label>
          </div>
        );
      case 'context':
        return (
          <div className="tab-panel">
            <label className="control-checkbox">
              <input
                type="checkbox"
                checked={showGoes}
                onChange={(e) => setShowGoes(e.target.checked)}
              />
              Overlay GOES/XRS data (0.1–0.8 nm)
            </label>
            <span className="tab-hint">
              First fetch of a day downloads the NetCDF from NOAA (~10–30 s); later requests use the cache.
            </span>
          </div>
        );
      case 'layers':
        return (
          <div className="tab-panel">
            {layers.length === 0 && failedStations.length === 0 && (
              <span className="tab-hint">Load one or more stations to manage layers.</span>
            )}
            {layers.map((layer) => {
              const ls = layerState[layer.station] ?? { visible: true, opacity: 1 };
              return (
                <div key={layer.station} className="layer-row tab-layer-row">
                  <label className="layer-name">
                    <input
                      type="checkbox"
                      checked={ls.visible}
                      onChange={(e) => setLayerVisible(layer.station, e.target.checked)}
                    />
                    <span title={layer.station}>{layer.station}</span>
                  </label>
                  <input
                    type="range"
                    className="control-slider"
                    min="0" max="1" step="0.05"
                    value={ls.opacity}
                    onChange={(e) => setLayerOpacity(layer.station, parseFloat(e.target.value))}
                    title={`Opacity: ${ls.opacity}`}
                  />
                </div>
              );
            })}
            {failedStations.map((f) => (
              <div key={f.station} className="layer-failed">
                ⚠ {f.station}: {f.reason}
              </div>
            ))}
          </div>
        );
      case 'tools':
        return (
          <div className="tab-panel">
            <button
              className={`btn-tool${rulerMode ? ' active' : ''}`}
              onClick={() => setRulerMode((r) => !r)}
              title="Click two points on the spectrogram to measure Δt, Δf and drift rate (MHz/s)"
            >
              📐 Drift ruler {rulerMode ? 'ON' : ''}
            </button>
            <button
              className="btn-tool"
              onClick={() => { setHeaderLayerIdx(0); setShowHeaderViewer(true); }}
              disabled={layers.length === 0}
              title="Inspect the FITS header of a loaded layer"
            >
              🗎 FITS header
            </button>
            {rulerMode && (
              <span className="tab-hint">
                Click two points on the plot — the drift readout appears in the header. Toggle off to clear.
              </span>
            )}
          </div>
        );
      default:
        return null;
    }
  }

  return (
    <div className="dashboard">

      {/* ── Sidebar: observation essentials only ── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>e-CALLISTO<br /><span>Spain</span></h1>
          <p className="sidebar-subtitle">Solar Spectrogram Portal</p>
        </div>

        <div className="sidebar-section">
          <h2 className="section-title">Observation</h2>

          {/* ── Station multi-select ── */}
          <div className="control-label">
            Stations
            {stationsSource && (
              <span
                title={stationsSource === 'ethz' ? 'Live list from ETHZ' : 'Static fallback list'}
                style={{ marginLeft: '0.4rem', fontSize: '0.65rem', color: stationsSource === 'ethz' ? '#38bdf8' : '#f59e0b', verticalAlign: 'middle' }}
              >
                {stationsSource === 'ethz' ? '● ETHZ' : '● local'}
              </span>
            )}
            {selectedStations.length > 0 && (
              <span style={{ fontSize: '0.65rem', color: '#38bdf8', marginLeft: '0.3rem' }}>
                {selectedStations.length} selected
              </span>
            )}
            <input
              type="text"
              className="control-input station-search"
              placeholder="Filter stations…"
              value={stationFilter}
              onChange={(e) => setStationFilter(e.target.value)}
            />
            <div className="station-checklist">
              {filteredStations.length === 0 && (
                <p className="files-hint" style={{ padding: '0.3rem 0.5rem' }}>No match.</p>
              )}
              {filteredStations.map((s) => (
                <label
                  key={s}
                  className={`station-check-row${selectedStations.includes(s) ? ' selected' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={selectedStations.includes(s)}
                    onChange={() => toggleStation(s)}
                  />
                  <span>{s}</span>
                </label>
              ))}
            </div>
          </div>

          <label className="control-label">
            Date
            <input
              type="date"
              className="control-input"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
        </div>

        {/* ── Burst / File selector ────────────────────────────────────────── */}
        <div className="sidebar-section burst-section">
            <h2 className="section-title">
              Burst / File
              {filesLoading && <span className="files-loading-dot" />}
              {!filesLoading && files.length > 0 && (
                <span style={{ color: '#4a7a9b', fontWeight: 400, marginLeft: '0.3rem' }}>
                  ({files.length})
                </span>
              )}
            </h2>

            {/* Primary-station picker: anchors the 15-min block for the others */}
            {selectedStations.length > 1 && (
              <label className="control-label" style={{ marginBottom: '0.4rem' }}>
                Primary station
                <select
                  className="control-input"
                  value={station ?? ''}
                  onChange={(e) => setStation(e.target.value)}
                >
                  {selectedStations.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
            )}

            {!station && <p className="files-hint">Select a station first.</p>}
            {station && filesLoading && <p className="files-hint">Querying ETHZ…</p>}
            {station && !filesLoading && files.length === 0 && <p className="files-hint">No files available.</p>}

            {!filesLoading && files.length > 0 && (
              <div className="burst-list">
                {Object.entries(
                  files.reduce((acc, f) => {
                    const h = f.time.slice(0, 2);
                    if (!acc[h]) acc[h] = [];
                    acc[h].push(f);
                    return acc;
                  }, {})
                )
                  .sort(([a], [b]) => Number(a) - Number(b))
                  .map(([hour, bursts]) => {
                    const collapsed = collapsedHours[hour] ?? false;
                    return (
                      <div key={hour} className="burst-hour-group">
                        <div
                          className="burst-hour-header collapsible"
                          onClick={() =>
                            setCollapsedHours((prev) => ({ ...prev, [hour]: !collapsed }))
                          }
                        >
                          <span className="chevron">{collapsed ? '▸' : '▾'}</span>
                          {hour}:xx UTC
                          <span className="hour-count">({bursts.length})</span>
                        </div>
                        {!collapsed && bursts.map((f) => {
                          const isCached = f.label.startsWith('★');
                          const displayLabel = isCached ? `★ ${f.time.slice(3)}` : f.time.slice(3);
                          return (
                            <button
                              key={f.filename}
                              className={`burst-chip ${selectedFile === f.filename ? 'active' : ''}`}
                              onClick={() => handleChipClick(f.filename)}
                              title={f.filename}
                            >
                              {displayLabel}
                            </button>
                          );
                        })}
                      </div>
                    );
                  })}
              </div>
            )}
            {files.length > 0 && (
              <p className="files-hint" style={{ marginTop: '0.3rem' }}>← → to step through files</p>
            )}
        </div>

        <div className="sidebar-section" style={{ flex: 'none' }}>
          <button
            className="btn-load"
            onClick={handleLoad}
            disabled={loadDisabled}
          >
            {hasLoaded ? '▶ Reload' : '▶ Load'}
          </button>
        </div>

        <div className="sidebar-status">
          <span className="status-dot" />
          Backend · port 8000
        </div>

        <div className="sidebar-footer">
          <div>Bachelor's Thesis — UAH · 2026</div>
          <div>Alfonso Muñoz Sevillano</div>
        </div>
      </aside>

      {/* ── Main area ── */}
      <main className="main-content">
        {/* Toolbar tabs (replaces the old crowded sidebar sections) */}
        <div className="top-tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab-btn${activeTab === t.id ? ' active' : ''}`}
              onClick={() => setActiveTab(activeTab === t.id ? null : t.id)}
            >
              {t.label}
              {t.id === 'layers' && layers.length > 0 && (
                <span className="tab-badge">{layers.length}</span>
              )}
            </button>
          ))}
        </div>
        {activeTab && renderTabPanel()}

        <Spectrogram
          layers={layers}
          layerState={layerState}
          failedStations={failedStations}
          date={date}
          showGoes={showGoes}
          colormap={colormap}
          zmin={useCustomZ ? zmin : null}
          zmax={useCustomZ ? zmax : null}
          triggerLoad={triggerLoad}
          hasLoaded={hasLoaded}
          loading={fetchLoading}
          error={fetchError}
          useSahanFilter={useSahanFilter}
          rfiParams={rfiParams}
          compareMode={compareMode}
          autoContrastZoom={autoContrastZoom}
          rulerMode={rulerMode}
        />
      </main>

      {/* ── FITS header viewer modal ── */}
      {showHeaderViewer && layers.length > 0 && (
        <div className="modal-overlay" onClick={() => setShowHeaderViewer(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>FITS header — {layers[headerLayerIdx]?.station}</h3>
              <button className="modal-close" onClick={() => setShowHeaderViewer(false)}>✕</button>
            </div>
            {layers.length > 1 && (
              <select
                className="control-input"
                style={{ margin: '0 1rem 0.5rem' }}
                value={headerLayerIdx}
                onChange={(e) => setHeaderLayerIdx(parseInt(e.target.value, 10))}
              >
                {layers.map((l, i) => (
                  <option key={l.station} value={i}>{l.station} · {l.filename}</option>
                ))}
              </select>
            )}
            <div className="modal-body">
              <table className="header-table">
                <tbody>
                  {Object.entries(layers[headerLayerIdx]?.fits_header ?? {}).map(([k, v]) => (
                    <tr key={k}>
                      <td className="header-key">{k}</td>
                      <td className="header-val">{String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
