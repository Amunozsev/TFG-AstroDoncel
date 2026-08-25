import { lazy, Suspense, useState, useEffect, useCallback, useRef } from 'react';
import { API_BASE_URL, apiFetch } from './api';
import { buildAnalysisManifest, downloadManifest } from './analysisManifest';
import './App.css';

const Spectrogram = lazy(() => import('./Spectrogram'));
const StationsMap = lazy(() => import('./StationsMap'));
const BurstCatalog = lazy(() => import('./BurstCatalog'));
const Statistics = lazy(() => import('./Statistics'));
const About = lazy(() => import('./About'));
const LightCurvePanel = lazy(() => import('./LightCurvePanel'));
const DailyOverview = lazy(() => import('./DailyOverview'));

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

function nextUtcDate(value) {
  const parsed = new Date(`${value}T00:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() + 1);
  return parsed.toISOString().slice(0, 10);
}

export default function App() {
  // Top-level view: the spectrogram portal or the world stations map.
  const [view, setView]                     = useState('portal');
  const [stations, setStations]             = useState(FALLBACK_STATIONS);
  const [stationsSource, setStationsSource] = useState('');
  const [stationDetails, setStationDetails] = useState({});
  const [stationRetentionDays, setStationRetentionDays] = useState(90);
  const [stationFilter, setStationFilter]   = useState('');
  // Primary station: drives the burst-file list and the 15-min sync block.
  // No station is preselected on startup — the user must pick one.
  const [station, setStation]               = useState(null);
  // All stations selected for multi-layer loading
  const [selectedStations, setSelectedStations] = useState([]);
  const [date, setDate]                     = useState(() => new Date().toISOString().slice(0, 10));
  const [overviewStart, setOverviewStart]   = useState(() => `${new Date().toISOString().slice(0, 10)}T00:00`);
  const [overviewEnd, setOverviewEnd]       = useState(() => `${nextUtcDate(new Date().toISOString().slice(0, 10))}T00:00`);

  // Daily burst list (primary station only)
  const [files, setFiles]                   = useState([]);
  const [filesLoading, setFilesLoading]     = useState(false);
  const [selectedFile, setSelectedFile]     = useState(null);
  const [focusCode, setFocusCode]           = useState('all');
  const [pendingEventTime, setPendingEventTime] = useState(null);
  const [collapsedHours, setCollapsedHours] = useState({});

  const [useSahanFilter, setSahan]          = useState(false);
  const [scaleMode, setScaleMode]           = useState('relative');
  const [rfiParams, setRfiParams]           = useState({
    zThresh: 6.0, occupancy: 0.15, minComponent: 9, impulsive: true,
  });
  const [showGoes, setShowGoes]             = useState(false);
  const [colormap, setColormap]             = useState('observatory');
  const [zmin, setZmin]                     = useState(-5);
  const [zmax, setZmax]                     = useState(30);
  const [useCustomZ, setUseCustomZ]         = useState(false);
  const [contrastPresets, setContrastPresets] = useState(() => {
    try { return JSON.parse(localStorage.getItem('astrodoncel.contrastPresets') ?? '[]'); }
    catch { return []; }
  });
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

  // Automatic burst detection (CNN+MIL): { [station]: BurstDetectResponse }
  const [burstResults, setBurstResults]     = useState({});
  const [burstDetecting, setBurstDetecting] = useState(false);
  const [taskStatus, setTaskStatus]         = useState(null);
  const taskRunRef = useRef(0);

  const exportAnalysisManifest = () => downloadManifest(buildAnalysisManifest({
    date,
    station,
    layers,
    processing: {
      rfi_enabled: useSahanFilter,
      rfi_parameters: rfiParams,
      intensity_scale: scaleMode,
      background_method: 'per-channel 25th percentile',
    },
    display: {
      colormap,
      comparison_mode: compareMode,
      manual_contrast: useCustomZ ? { zmin, zmax } : null,
      auto_contrast_on_zoom: autoContrastZoom,
    },
    solarContext: { goes_xrs_overlay: showGoes, wavelength_nm: showGoes ? '0.1–0.8' : null },
  }));

  useEffect(() => {
    if (!showHeaderViewer) return undefined;
    const closeOnEscape = (event) => { if (event.key === 'Escape') setShowHeaderViewer(false); };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [showHeaderViewer]);

  // ── Load station list ─────────────────────────────────────────────────────
  useEffect(() => {
    let disposed = false;
    async function loadStations() {
      try {
        const res = await apiFetch('/api/stations');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!disposed && data.stations?.length > 0) {
          const nextStations = data.stations;
          setStations(nextStations);
          setStationsSource(data.source);
          setStationRetentionDays(data.retention_days ?? 90);
          setStationDetails(Object.fromEntries(
            (data.details ?? []).map((item) => [item.station, item]),
          ));
          setStation((current) => current && nextStations.includes(current) ? current : null);
          setSelectedStations((current) => current.filter((item) => nextStations.includes(item)));
        }
      } catch (err) {
        if (!disposed) {
          console.warn('Station list from API failed, using the last available inventory:', err.message);
          setStationsSource((current) => current || 'static');
        }
      }
    }
    loadStations();
    const refreshId = window.setInterval(loadStations, 15 * 60 * 1000);
    return () => {
      disposed = true;
      window.clearInterval(refreshId);
    };
  }, []);

  // ── Reload burst list when primary station or date changes ────────────────
  const loadFiles = useCallback(async (st, dt, signal) => {
    setFiles([]);
    setSelectedFile(null);
    setCollapsedHours({});
    if (!st) return;
    setFilesLoading(true);
    try {
      const res = await apiFetch(
        `/api/files?station=${encodeURIComponent(st)}&date=${encodeURIComponent(dt)}`,
        { signal },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setFiles(data.files ?? []);
      if (data.files?.length > 0) {
        setSelectedFile(data.files[0].filename);
      }
    } catch (err) {
      if (!signal.aborted) console.warn('Could not load burst list:', err.message);
    } finally {
      if (!signal.aborted) setFilesLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => loadFiles(station, date, controller.signal));
    return () => controller.abort();
  }, [station, date, loadFiles]);

  useEffect(() => {
    taskRunRef.current += 1;
    queueMicrotask(() => setTaskStatus(null));
  }, [station, date]);

  useEffect(() => {
    if (!pendingEventTime || files.length === 0) return;
    const target = new Date(pendingEventTime);
    const targetSeconds = target.getUTCHours() * 3600 + target.getUTCMinutes() * 60 + target.getUTCSeconds();
    const seconds = (value) => value.time.split(':').reduce(
      (sum, part, index) => sum + Number(part) * [3600, 60, 1][index],
      0,
    );
    const ordered = [...files].sort((a, b) => seconds(a) - seconds(b));
    // e-CALLISTO filenames identify the start of a time block. The event
    // belongs to the latest block that started at or before its UTC time.
    const nearest = [...ordered].reverse().find((item) => seconds(item) <= targetSeconds) ?? ordered[0];
    queueMicrotask(() => {
      setSelectedFile(nearest.filename);
      setPendingEventTime(null);
      setHasLoaded(true);
      setTriggerLoad((value) => value + 1);
    });
  }, [files, pendingEventTime]);

  // ── Fetch spectrogram layers on explicit Load ─────────────────────────────
  useEffect(() => {
    if (!hasLoaded || triggerLoad === 0) return;
    if (selectedStations.length === 0) return;

    const controller = new AbortController();
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
            scale_mode: scaleMode,
            max_time_bins: '1500',
            ...rfiQS,
          });
          if (selectedFile) params.set('filename', selectedFile);
          // Primary station first so the backend anchors the 15-min block to it
          const ordered = [station, ...selectedStations.filter((s) => s !== station)]
            .filter(Boolean);
          ordered.forEach((s) => params.append('stations', s));
          const res = await apiFetch(`/api/spectrogram/combine?${params}`, { signal: controller.signal });
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
            scale_mode: scaleMode,
            max_time_bins: '1500',
            ...rfiQS,
          });
          if (selectedFile) params.set('filename', selectedFile);
          const res = await apiFetch(`/api/spectrogram?${params}`, { signal: controller.signal });
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
        if (!controller.signal.aborted) {
          setFetchError(err.message);
          setLayers([]);
          setFailedStations([]);
        }
      } finally {
        if (!controller.signal.aborted) setFetchLoading(false);
      }
    }

    fetchLayers();
    return () => controller.abort();
  }, [triggerLoad]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleLoad() {
    setHasLoaded(true);
    setBurstResults({}); // stale detections don't apply to a new load
    setTriggerLoad((n) => n + 1);
  }

  function changeObservationDate(nextDate) {
    setDate(nextDate);
    setOverviewStart(`${nextDate}T00:00`);
    setOverviewEnd(`${nextUtcDate(nextDate)}T00:00`);
  }

  // ── Open a station from the map: select it and load its spectrograms ───────
  function handleOpenStation(st) {
    setSelectedStations([st]);
    setStation(st);
    setStationFilter('');
    setSelectedFile(null);      // let the backend pick the first file of the day
    setView('portal');
    setHasLoaded(true);
    setBurstResults({});
    setTriggerLoad((n) => n + 1);
  }

  function handleOpenEvent(event, requestedStation = null) {
    const targetStation = requestedStation ?? event.stations?.[0];
    if (!targetStation) return;
    setBurstResults({});
    changeObservationDate(event.started_at.slice(0, 10));
    setSelectedStations([targetStation]);
    setStation(targetStation);
    setPendingEventTime(event.started_at);
    setView('portal');
  }

  // ── Automatic burst detection on every loaded layer ───────────────────────
  async function handleDetectBursts() {
    if (layers.length === 0 || burstDetecting) return;
    setBurstDetecting(true);
    try {
      const results = await Promise.all(
        layers.map(async (l) => {
          const params = new URLSearchParams({
            station: l.station,
            date: l.date,
            filename: l.filename,
          });
          try {
            const res = await apiFetch(`/api/burst/detect?${params}`);
            if (!res.ok) {
              const body = await res.json().catch(() => ({}));
              return [l.station, { available: false, reason: body.detail ?? `Error ${res.status}` }];
            }
            return [l.station, await res.json()];
          } catch (err) {
            return [l.station, { available: false, reason: err.message }];
          }
        })
      );
      setBurstResults(Object.fromEntries(results));
    } finally {
      setBurstDetecting(false);
    }
  }

  async function startTask(type, options = {}) {
    if (!station) return;
    const runId = ++taskRunRef.current;
    const context = { station, date };
    setTaskStatus({ status: 'submitting', progress: 0, type, ...context });
    try {
      const response = await apiFetch('/api/tasks', {
        method: 'POST', body: JSON.stringify({ type, station, date, options }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const created = await response.json();
      let current = created;
      while (['queued', 'running', 'cancel_requested'].includes(current.status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        if (taskRunRef.current !== runId) return;
        const poll = await apiFetch(`/api/tasks/${created.id}`);
        if (!poll.ok) throw new Error(`HTTP ${poll.status}`);
        current = await poll.json();
        if (taskRunRef.current === runId) setTaskStatus({ ...current, ...context });
      }
    } catch (cause) {
      if (taskRunRef.current === runId) {
        setTaskStatus({ status: 'failed', error: cause.message, type, ...context });
      }
    }
  }

  function handleChipClick(filename) {
    setSelectedFile(filename);
    setHasLoaded(true);
    setBurstResults({});
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
  }, [files, selectedFile]);

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

  function saveContrastPreset() {
    const next = [...contrastPresets, { name: `Preset ${contrastPresets.length + 1}`, zmin, zmax, colormap }].slice(-8);
    setContrastPresets(next);
    localStorage.setItem('astrodoncel.contrastPresets', JSON.stringify(next));
  }

  function applyContrastPreset(index) {
    const preset = contrastPresets[index];
    if (!preset) return;
    setZmin(preset.zmin); setZmax(preset.zmax); setColormap(preset.colormap); setUseCustomZ(true);
  }

  function startOverview(requestedStations) {
    if (!overviewStart || !overviewEnd || requestedStations.length === 0) return;
    const toUtcIso = (value) => new Date(`${value}:00Z`).toISOString();
    startTask('spectral_overview', {
      stations: requestedStations,
      start_at: toUtcIso(overviewStart),
      end_at: toUtcIso(overviewEnd),
    });
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
              Intensity scale
              <select className="control-input" value={scaleMode} onChange={(event) => setScaleMode(event.target.value)}>
                <option value="relative">Relative detector digits</option>
                <option value="median_db">median_dB calibration</option>
              </select>
            </label>
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
            <div className="tab-group">
              <button className="btn-apply" onClick={saveContrastPreset}>Save contrast preset</button>
              {contrastPresets.length > 0 && <label className="tab-field">Saved preset<select className="control-input" defaultValue="" onChange={(event) => applyContrastPreset(Number(event.target.value))}><option value="" disabled>Select…</option>{contrastPresets.map((preset, index) => <option key={`${preset.name}-${index}`} value={index}>{preset.name}</option>)}</select></label>}
            </div>
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
              Drift ruler {rulerMode ? 'ON' : ''}
            </button>
            <button
              className="btn-tool"
              onClick={() => { setHeaderLayerIdx(0); setShowHeaderViewer(true); }}
              disabled={layers.length === 0}
              title="Inspect the FITS header of a loaded layer"
            >
              FITS header
            </button>
            <button
              className="btn-tool"
              onClick={handleDetectBursts}
              disabled={layers.length === 0 || burstDetecting}
              title="Run the trained CNN+MIL classifier (Sahan's Burst_No_Burst) on every loaded layer"
            >
              {burstDetecting ? 'Detecting…' : 'Detect current file (ML)'}
            </button>
            <fieldset className="overview-task-controls">
              <legend>Spectral overview interval (UTC)</legend>
              <label>
                From
                <input type="datetime-local" value={overviewStart} onChange={(event) => setOverviewStart(event.target.value)} />
              </label>
              <label>
                To
                <input type="datetime-local" value={overviewEnd} onChange={(event) => setOverviewEnd(event.target.value)} />
              </label>
              <button
                className="btn-tool"
                onClick={() => startOverview(selectedStations)}
                disabled={!station || selectedStations.length === 0 || ['submitting', 'queued', 'running'].includes(taskStatus?.status)}
              >
                Overview · selected ({selectedStations.length})
              </button>
              <button
                className="btn-tool"
                onClick={() => startOverview(stations)}
                disabled={!station || stations.length === 0 || ['submitting', 'queued', 'running'].includes(taskStatus?.status)}
              >
                Overview · all known ({stations.length})
              </button>
            </fieldset>
            <button className="btn-tool" onClick={() => {
              const current = Math.max(0, files.findIndex((file) => file.filename === selectedFile));
              startTask('combine_time', { filenames: files.slice(current, current + 4).map((file) => file.filename) });
            }} disabled={!station || files.length < 2 || ['submitting', 'queued', 'running'].includes(taskStatus?.status)} title="Merge the current FITS block and up to three following compatible blocks into one continuous spectrogram">Combine next blocks</button>
            <p className="tool-help">Combine next blocks joins the current time block with up to three following blocks from the same station and receiver. It does not mix stations.</p>
            {layers[0] && <>
              <a className="btn-tool" href={`${API_BASE_URL}/api/files/download?${new URLSearchParams({ station: layers[0].station, date: layers[0].date, filename: layers[0].filename })}`}>Download FITS</a>
              <a className="btn-tool" href={`${API_BASE_URL}/api/spectrogram/export?${new URLSearchParams({ station: layers[0].station, date: layers[0].date, filename: layers[0].filename, rfi: useSahanFilter, rfi_z_thresh: rfiParams.zThresh, rfi_occupancy: rfiParams.occupancy, rfi_min_component: rfiParams.minComponent, rfi_impulsive: rfiParams.impulsive })}`}>Export processed FITS</a>
              <button className="btn-tool" type="button" onClick={exportAnalysisManifest}>Export analysis manifest</button>
            </>}
            <p className="tool-help">The analysis manifest records selected FITS identifiers, units, processing settings, display configuration and scientific provenance without exposing local paths.</p>
            {taskStatus && <span className={`task-status ${taskStatus.status}`} role="status">Job: {taskStatus.status}{Number.isFinite(taskStatus.progress) ? ` · ${Math.round(taskStatus.progress * 100)}%` : ''}{taskStatus.error ? ` · ${taskStatus.error}` : ''}{taskStatus.result?.artifact_url ? <a href={`${API_BASE_URL}${taskStatus.result.artifact_url}`}>Open result</a> : null}</span>}
            {Object.entries(burstResults).map(([st, r]) => (
              <span
                key={st}
                className={`stat-chip${r.available && (r.is_burst || r.is_candidate) ? ' burst-hit' : ''}`}
                title={
                  r.available
                    ? `Model ${r.model_version} · ${r.n_windows} windows · ${r.inference_ms} ms`
                    : r.reason
                }
              >
                {r.available
                  ? `${st}: p=${r.file_score.toFixed(2)}${r.events?.length ? ` · ${r.is_burst ? 'event' : 'candidate'} ${r.events.length}` : ' · no burst'}`
                  : `${st}: unavailable`}
              </span>
            ))}
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
    <div className="app-root">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <nav className="app-nav" aria-label="Primary navigation">
        <span className="app-brand">e-CALLISTO<b>Spain</b></span>
        <div className="app-nav-tabs">
          <button
            className={view === 'portal' ? 'active' : ''}
            onClick={() => setView('portal')}
          >
            Portal
          </button>
          <button
            className={view === 'map' ? 'active' : ''}
            onClick={() => setView('map')}
          >
            Stations Map
          </button>
          <button className={view === 'catalog' ? 'active' : ''} onClick={() => setView('catalog')}>Burst Reports</button>
          <button className={view === 'statistics' ? 'active' : ''} onClick={() => setView('statistics')}>Statistics</button>
          <button className={view === 'about' ? 'active' : ''} onClick={() => setView('about')}>About</button>
        </div>
        <span className="app-nav-spacer" />
      </nav>

      <Suspense fallback={<div className="page-shell" role="status">Loading view…</div>}>
      {view === 'catalog' ? (
        <BurstCatalog onOpenEvent={handleOpenEvent} />
      ) : view === 'statistics' ? (
        <Statistics onOpenStation={handleOpenStation} onOpenEvent={handleOpenEvent} />
      ) : view === 'about' ? (
        <About />
      ) : view === 'map' ? (
        <StationsMap onOpenStation={handleOpenStation} />
      ) : (
        <div className="dashboard">

      {/* ── Sidebar: observation essentials only ── */}
      <aside className={`sidebar${files.length > 0 ? ' has-files' : ''}`}>
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
                title={stationsSource.includes('ethz') ? `Live ETHZ inventory plus stations seen in the last ${stationRetentionDays} days` : 'Local bootstrap list'}
                style={{ marginLeft: '0.4rem', fontSize: '0.65rem', color: stationsSource.includes('ethz') ? '#38bdf8' : '#f59e0b', verticalAlign: 'middle' }}
              >
                {stationsSource.includes('ethz') ? '● live + recent' : '● local'}
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
                  <i
                    className={`station-status-dot ${stationDetails[s]?.active ? 'active' : 'inactive'}`}
                    title={stationDetails[s]?.active ? 'Active on the latest archive day' : `Inactive on the latest archive day${stationDetails[s]?.last_seen_at ? ` · last seen ${stationDetails[s].last_seen_at.slice(0, 10)}` : ''}`}
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
              onChange={(e) => changeObservationDate(e.target.value)}
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

            {files.length > 0 && (
              <label className="control-label focus-filter">
                Focus code
                <select className="control-input" value={focusCode} onChange={(event) => setFocusCode(event.target.value)}>
                  <option value="all">All receivers</option>
                  {[...new Set(files.map((file) => file.focus_code).filter(Boolean))].sort().map((code) => (
                    <option key={code} value={code}>{code}</option>
                  ))}
                </select>
              </label>
            )}

            {!filesLoading && files.length > 0 && (
              <div className="burst-list">
                {Object.entries(
                  files.filter((file) => focusCode === 'all' || file.focus_code === focusCode).reduce((acc, f) => {
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
      <main className="main-content" id="main-content" tabIndex="-1">
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
          burstResults={burstResults}
        />
        <LightCurvePanel key={layers[0] ? `${layers[0].station}:${layers[0].date}:${layers[0].filename}` : 'empty'} layer={layers[0]} />
        {taskStatus?.status === 'succeeded' && taskStatus.type === 'spectral_overview' && taskStatus.result?.artifact_url && <DailyOverview key={taskStatus.id} artifactUrl={taskStatus.result.artifact_url} />}
      </main>

      {/* ── FITS header viewer modal ── */}
      {showHeaderViewer && layers.length > 0 && (
        <div className="modal-overlay" onClick={() => setShowHeaderViewer(false)}>
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="fits-header-title" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 id="fits-header-title">FITS header — {layers[headerLayerIdx]?.station}</h3>
              <button className="modal-close" aria-label="Close FITS header" autoFocus onClick={() => setShowHeaderViewer(false)}>Close</button>
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
      )}
      </Suspense>
    </div>
  );
}
