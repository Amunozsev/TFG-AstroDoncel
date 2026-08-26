import { lazy, Suspense, useState, useEffect, useCallback, useRef } from 'react';
import { API_BASE_URL, apiFetch } from './api';
import { buildAnalysisManifest, downloadManifest } from './analysisManifest';
import { describeBurstResult } from './burstResult';
import { fileForEvent } from './eventNavigation';
import './App.css';

const Spectrogram = lazy(() => import('./Spectrogram'));
const StationsMap = lazy(() => import('./StationsMap'));
const BurstCatalog = lazy(() => import('./BurstCatalog'));
const Statistics = lazy(() => import('./Statistics'));
const About = lazy(() => import('./About'));
const LightCurvePanel = lazy(() => import('./LightCurvePanel'));
const LightCurveResult = lazy(() => import('./LightCurvePanel').then((module) => ({ default: module.LightCurveResult })));
const DailyOverview = lazy(() => import('./DailyOverview'));
const CombinedSpectrogram = lazy(() => import('./CombinedSpectrogram'));

const TABS = [
  { id: 'processing', label: 'Processing', icon: 'sliders' },
  { id: 'display', label: 'Display', icon: 'display' },
  { id: 'layers', label: 'Layers', icon: 'layers' },
  { id: 'lightcurve', label: 'Light curve', icon: 'curve' },
  { id: 'tools', label: 'Tools', icon: 'tools' },
];

const PANEL_TITLES = Object.fromEntries(TABS.map((item) => [item.id, item.label]));
const MAX_SPECTROGRAM_LAYERS = 6;

const ICON_PATHS = {
  sliders: 'M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M6 14v6',
  display: 'M4 5h16v11H4zM8 20h8M12 16v4',
  layers: 'M12 3 3 8l9 5 9-5-9-5Zm-7 9 7 4 7-4M5 16l7 4 7-4',
  curve: 'M3 17c3-7 5-8 8-3s5 3 10-7M3 21h18',
  tools: 'M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6',
  sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-5v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4',
  moon: 'M20 15.2A8.4 8.4 0 0 1 8.8 4 8.5 8.5 0 1 0 20 15.2Z',
};

function Icon({ name }) {
  return (
    <svg className="ui-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

function initialTheme() {
  try { return localStorage.getItem('astrodoncel.theme') === 'light' ? 'light' : 'dark'; }
  catch { return 'dark'; }
}

function nextUtcDate(value) {
  const parsed = new Date(`${value}T00:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() + 1);
  return parsed.toISOString().slice(0, 10);
}

function describeStationSource(source, retentionDays) {
  if (!source) return null;
  if (source.includes('ethz')) {
    return {
      label: '● live + recent',
      title: `Live ETHZ inventory plus stations seen in the last ${retentionDays} days`,
      live: true,
    };
  }
  if (source === 'bootstrap') {
    return {
      label: '● bootstrap',
      title: 'Local bootstrap list; the live archive is unavailable',
      live: false,
    };
  }
  return {
    label: '● unavailable',
    title: 'Station inventory is temporarily unavailable',
    live: false,
  };
}

export default function App() {
  const [theme, setTheme]                   = useState(initialTheme);
  // Top-level view: the spectrogram portal or the world stations map.
  const [view, setView]                     = useState('portal');
  const [stations, setStations]             = useState([]);
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
  const [filesContext, setFilesContext]     = useState(null);
  const [filesLoading, setFilesLoading]     = useState(false);
  const [selectedFile, setSelectedFile]     = useState(null);
  const [focusCode, setFocusCode]           = useState('all');
  const [pendingEvent, setPendingEvent]     = useState(null);
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
  const [lightCurveResult, setLightCurveResult] = useState(null);
  const taskRunRef = useRef(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    try { localStorage.setItem('astrodoncel.theme', theme); } catch { /* storage can be unavailable */ }
  }, [theme]);

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
    if (!showHeaderViewer && !activeTab) return undefined;
    const closeOnEscape = (event) => {
      if (event.key !== 'Escape') return;
      if (showHeaderViewer) setShowHeaderViewer(false);
      else setActiveTab(null);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [activeTab, showHeaderViewer]);

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
          console.warn('Station list refresh failed; keeping the last available inventory:', err.message);
          setStationsSource((current) => current || 'unavailable');
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
    setFilesContext(null);
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
      if (signal.aborted) return;
      const nextFiles = data.files ?? [];
      setFiles(nextFiles);
      setFilesContext({ station: st, date: dt });
      if (nextFiles.length > 0) {
        setSelectedFile(nextFiles[0].filename);
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
    if (!pendingEvent) return;
    if (
      filesContext?.station === pendingEvent.station
      && filesContext?.date === pendingEvent.date
      && files.length === 0
    ) {
      queueMicrotask(() => setPendingEvent(null));
      return;
    }
    // e-CALLISTO filenames identify the start of a time block. The event
    // belongs to the latest block that started at or before its UTC time.
    const nearest = fileForEvent(files, filesContext, pendingEvent);
    if (!nearest) return;
    queueMicrotask(() => {
      setSelectedFile(nearest.filename);
      setPendingEvent(null);
      setHasLoaded(true);
      setTriggerLoad((value) => value + 1);
    });
  }, [files, filesContext, pendingEvent]);

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
    setFiles([]);
    setFilesContext(null);
    setPendingEvent(null);
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
    const targetDate = event.started_at.slice(0, 10);
    // Invalidate the previous observation synchronously. Otherwise the event
    // selector can briefly pair the old station's filename with the new
    // station/date before /api/files has returned.
    setHasLoaded(false);
    setFiles([]);
    setFilesContext(null);
    setSelectedFile(null);
    setLayers([]);
    setFailedStations([]);
    setFetchError(null);
    setTriggerLoad((value) => value + 1); // abort an in-flight layer request
    setBurstResults({});
    changeObservationDate(targetDate);
    setSelectedStations([targetStation]);
    setStation(targetStation);
    setPendingEvent({ station: targetStation, date: targetDate, startedAt: event.started_at });
    setView('portal');
  }

  // ── Automatic burst detection on the primary (current) FITS block ─────────
  async function handleDetectBursts() {
    if (layers.length === 0 || burstDetecting) return;
    setBurstDetecting(true);
    setBurstResults({});
    const layer = layers[0];
    try {
      const params = new URLSearchParams({
        station: layer.station,
        date: layer.date,
        filename: layer.filename,
      });
      const res = await apiFetch(`/api/burst/detect?${params}`, { timeoutMs: 90_000 });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Error ${res.status}`);
      }
      setBurstResults({ [layer.station]: await res.json() });
    } catch (err) {
      setBurstResults({ [layer.station]: { available: false, reason: err.message } });
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
      if (selectedStations.length >= MAX_SPECTROGRAM_LAYERS) return;
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

  function showResult(id) {
    setActiveTab(null);
    window.setTimeout(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 0);
  }

  const loadDisabled =
    !date ||
    selectedStations.length === 0 ||
    (files.length > 0 && !selectedFile);

  const selectedFileIndex = files.findIndex((file) => file.filename === selectedFile);
  const combineFilenames = selectedFileIndex < 0
    ? []
    : files.slice(selectedFileIndex, selectedFileIndex + 4).map((file) => file.filename);

  const currentLightCurve = lightCurveResult
    && layers[0]
    && lightCurveResult.source.station === layers[0].station
    && lightCurveResult.source.date === layers[0].date
    && lightCurveResult.source.filename === layers[0].filename
    ? lightCurveResult
    : null;
  const primaryTimeRange = layers[0]?.time_axis?.length > 1
    ? [layers[0].time_axis[0], layers[0].time_axis.at(-1)]
    : undefined;

  const filteredStations = stationFilter
    ? stations.filter((s) => s.toUpperCase().includes(stationFilter.toUpperCase()))
    : stations;
  const stationSourceStatus = describeStationSource(stationsSource, stationRetentionDays);

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
      case 'lightcurve':
        return (
          <LightCurvePanel
            key={layers[0] ? `${layers[0].station}:${layers[0].date}:${layers[0].filename}` : 'empty'}
            layer={layers[0]}
            theme={theme}
            embedded
            onCurve={(result) => {
              setLightCurveResult(result);
              setActiveTab(null);
            }}
          />
        );
      case 'tools':
        return (
          <div className="tool-sections">
            <section className="tool-section" aria-labelledby="inspect-tools-title">
              <div className="tool-section-heading">
                <div><span className="section-kicker">Current FITS</span><h3 id="inspect-tools-title">Inspect</h3></div>
                <p>Measurements and diagnostics for the loaded block.</p>
              </div>
              <div className="tool-action-grid">
                <button
                  className={`btn-tool${rulerMode ? ' active' : ''}`}
                  onClick={() => setRulerMode((current) => !current)}
                  title="Click two points on the spectrogram to measure Δt, Δf and drift rate (MHz/s)"
                >
                  Drift ruler {rulerMode ? 'on' : ''}
                </button>
                <button className="btn-tool" onClick={() => { setHeaderLayerIdx(0); setShowHeaderViewer(true); }} disabled={layers.length === 0} title="Show scientific metadata stored in the current FITS header">FITS header</button>
                <button
                  className="btn-tool"
                  onClick={handleDetectBursts}
                  disabled={layers.length === 0 || burstDetecting}
                  title="Classify the primary FITS block with the experimental CNN+MIL model"
                >
                  {burstDetecting ? 'Detecting…' : 'Detect current file (ML)'}
                </button>
              </div>
              {rulerMode && <p className="tool-help">Select two points on the plot. The header reports Δt, Δf and drift rate.</p>}
              {burstDetecting && <p className="detection-pending" role="status">Running experimental inference on the current FITS block…</p>}
              {Object.entries(burstResults).map(([st, result]) => {
                const summary = describeBurstResult(result);
                return (
                  <article key={st} className={`detection-result ${summary.status}`} aria-live="polite">
                    <header><strong>{st}</strong><span>{summary.label}</span></header>
                    <p>{summary.detail}</p>
                    {result.available && (
                      <dl>
                        <div><dt>Probability</dt><dd>{result.file_score.toFixed(3)}</dd></div>
                        <div><dt>Burst threshold</dt><dd>{result.threshold.toFixed(3)}</dd></div>
                        <div><dt>Model</dt><dd>{result.model_version}</dd></div>
                      </dl>
                    )}
                  </article>
                );
              })}
            </section>

            <section className="tool-section" aria-labelledby="overview-tools-title">
              <div className="tool-section-heading">
                <div><span className="section-kicker">Selected stations</span><h3 id="overview-tools-title">Spectral overview</h3></div>
                <p>Build a reduced UTC view without blocking the portal.</p>
              </div>
              <fieldset className="overview-task-controls">
                <legend className="sr-only">Spectral overview interval in UTC</legend>
                <label>From<input type="datetime-local" value={overviewStart} onChange={(event) => setOverviewStart(event.target.value)} /></label>
                <label>To<input type="datetime-local" value={overviewEnd} onChange={(event) => setOverviewEnd(event.target.value)} /></label>
                <button
                  className="btn-primary tool-primary-action"
                  onClick={() => startOverview(selectedStations)}
                  disabled={!station || selectedStations.length === 0 || ['submitting', 'queued', 'running'].includes(taskStatus?.status)}
                  title="Build a reduced long-interval spectrogram for the selected stations"
                >
                  Create overview ({selectedStations.length})
                </button>
              </fieldset>
              <p className="tool-help">Uses only the stations selected in the observation sidebar. Large intervals may take several minutes.</p>
              {taskStatus && (
                <div className={`task-progress-card ${taskStatus.status}`} role="status">
                  <span>Job · {taskStatus.status}</span>
                  <strong>{Number.isFinite(taskStatus.progress) ? `${Math.round(taskStatus.progress * 100)}%` : '—'}</strong>
                  <div className="task-progress-track"><i style={{ transform: `scaleX(${taskStatus.progress ?? 0})` }} /></div>
                  {taskStatus.error && <p>{taskStatus.error}</p>}
                  {taskStatus.status === 'succeeded' && taskStatus.type === 'combine_time' && (
                    <>
                      <p>{taskStatus.result?.files ?? combineFilenames.length} blocks combined into one continuous spectrogram.</p>
                      <button type="button" className="task-result-action" onClick={() => showResult('combined-spectrogram-result')}>
                        Show combined spectrogram
                      </button>
                    </>
                  )}
                  {taskStatus.result?.artifact_url && (
                    <a href={`${API_BASE_URL}${taskStatus.result.artifact_url}`}>
                      View {taskStatus.type === 'combine_time' ? 'combined' : 'overview'} data (JSON)
                    </a>
                  )}
                </div>
              )}
            </section>

            <details className="tool-disclosure">
              <summary>Data &amp; exports <span>Advanced actions</span></summary>
              <div className="tool-disclosure-body">
                <button className="btn-tool" onClick={() => {
                  startTask('combine_time', { filenames: combineFilenames });
                }} disabled={!station || combineFilenames.length < 2 || ['submitting', 'queued', 'running'].includes(taskStatus?.status)} title="Join the current FITS block with up to three following blocks when their frequency axes are compatible">
                  Combine current + next blocks
                </button>
                {layers[0] && <>
                  <a className="btn-tool" title="Download the unmodified source observation" href={`${API_BASE_URL}/api/files/download?${new URLSearchParams({ station: layers[0].station, date: layers[0].date, filename: layers[0].filename })}`}>Download original FITS</a>
                  <a className="btn-tool" title="Export the displayed processing result and its scientific axes as FITS" href={`${API_BASE_URL}/api/spectrogram/export?${new URLSearchParams({ station: layers[0].station, date: layers[0].date, filename: layers[0].filename, rfi: useSahanFilter, rfi_z_thresh: rfiParams.zThresh, rfi_occupancy: rfiParams.occupancy, rfi_min_component: rfiParams.minComponent, rfi_impulsive: rfiParams.impulsive })}`}>Export processed FITS</a>
                  <button className="btn-tool" type="button" onClick={exportAnalysisManifest} title="Save selected files, units, processing settings and provenance as JSON">Export analysis manifest</button>
                </>}
                <p className="tool-help">Combining starts at the selected block and joins up to three following blocks from the same station when their frequency axes are compatible. The result appears as one continuous spectrogram below the current observation.</p>
              </div>
            </details>

            <details className="tool-disclosure">
              <summary>Tool guide <span>Short explanations</span></summary>
              <dl className="tool-guide">
                <div><dt>Drift ruler</dt><dd>Two plot clicks measure elapsed time, frequency change and drift rate in MHz/s.</dd></div>
                <div><dt>ML detection</dt><dd>Classifies the current primary FITS block; it is experimental and always requires scientific review.</dd></div>
                <div><dt>Spectral overview</dt><dd>Reduces a longer UTC interval into an exploratory view and runs it in the persistent worker.</dd></div>
                <div><dt>Combine next blocks</dt><dd>Joins the current block and up to three following blocks only when station and receiver are compatible.</dd></div>
              </dl>
            </details>
          </div>
        );
      default:
        return null;
    }
  }

  return (
    <div className="app-root" data-theme={theme}>
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <nav className="app-nav" aria-label="Primary navigation">
        <span className="app-brand"><b>AstroDoncel</b><small>e-CALLISTO solar archive</small></span>
        <div className="app-nav-tabs">
          <button
            className={view === 'portal' ? 'active' : ''}
            onClick={() => setView('portal')}
          >
            Spectrograms
          </button>
          <button
            className={view === 'map' ? 'active' : ''}
            onClick={() => setView('map')}
          >
            Stations
          </button>
          <button className={view === 'catalog' ? 'active' : ''} onClick={() => setView('catalog')}>Burst Reports</button>
          <button className={view === 'statistics' ? 'active' : ''} onClick={() => setView('statistics')}>Statistics</button>
          <button className={view === 'about' ? 'active' : ''} onClick={() => setView('about')}>About</button>
        </div>
        <span className="app-nav-spacer" />
        <button
          type="button"
          className="theme-toggle"
          onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
          <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
        </button>
      </nav>

      <Suspense fallback={<div className="page-shell" role="status">Loading view…</div>}>
      {view === 'catalog' ? (
        <BurstCatalog onOpenEvent={handleOpenEvent} />
      ) : view === 'statistics' ? (
        <Statistics onOpenStation={handleOpenStation} onOpenEvent={handleOpenEvent} theme={theme} />
      ) : view === 'about' ? (
        <About />
      ) : view === 'map' ? (
        <StationsMap onOpenStation={handleOpenStation} theme={theme} />
      ) : (
        <div className="dashboard">

      {/* ── Sidebar: observation essentials only ── */}
      <aside className={`sidebar${files.length > 0 ? ' has-files' : ''}`}>
        <div className="sidebar-header">
          <h1>Observation workspace</h1>
          <p className="sidebar-subtitle">Stations, date and FITS block</p>
        </div>

        <div className="sidebar-section">
          <h2 className="section-title">Observation</h2>

          {/* ── Station multi-select ── */}
          <div className="control-label">
            Stations
            {stationSourceStatus && (
              <span
                title={stationSourceStatus.title}
                style={{ marginLeft: '0.4rem', fontSize: '0.65rem', color: stationSourceStatus.live ? '#38bdf8' : '#f59e0b', verticalAlign: 'middle' }}
              >
                {stationSourceStatus.label}
              </span>
            )}
            {selectedStations.length > 0 && (
              <span style={{ fontSize: '0.65rem', color: '#38bdf8', marginLeft: '0.3rem' }}>
                {selectedStations.length}/{MAX_SPECTROGRAM_LAYERS} selected
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
                <p className="files-hint" style={{ padding: '0.3rem 0.5rem' }}>
                  {!stationsSource ? 'Loading stations…' : stationFilter ? 'No match.' : 'No stations available.'}
                </p>
              )}
              {filteredStations.map((s) => (
                <label
                  key={s}
                  className={`station-check-row${selectedStations.includes(s) ? ' selected' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={selectedStations.includes(s)}
                    disabled={!selectedStations.includes(s) && selectedStations.length >= MAX_SPECTROGRAM_LAYERS}
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
            {selectedStations.length >= MAX_SPECTROGRAM_LAYERS && <p className="files-hint">Maximum: {MAX_SPECTROGRAM_LAYERS} simultaneous layers.</p>}
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

      </aside>

      {/* ── Main area ── */}
      <main className="main-content" id="main-content" tabIndex="-1">
        <div className="workspace-toolbar" aria-label="Spectrogram controls">
          <div className="workspace-toolbar-actions">
          {TABS.slice(0, 2).map((t) => (
            <button
              key={t.id}
              className={`tab-btn${activeTab === t.id ? ' active' : ''}`}
              onClick={() => setActiveTab(activeTab === t.id ? null : t.id)}
              aria-expanded={activeTab === t.id}
            >
              <Icon name={t.icon} />
              {t.label}
            </button>
          ))}
          <button
            type="button"
            className={`tab-btn quick-toggle${showGoes ? ' active' : ''}`}
            onClick={() => setShowGoes((current) => !current)}
            aria-pressed={showGoes}
            title="Overlay GOES/XRS-B solar flux (0.1–0.8 nm)"
          >
            <Icon name="sun" />GOES<span className="toggle-state">{showGoes ? 'On' : 'Off'}</span>
          </button>
          {TABS.slice(2).map((t) => (
            <button
              key={t.id}
              className={`tab-btn${activeTab === t.id ? ' active' : ''}`}
              onClick={() => setActiveTab(activeTab === t.id ? null : t.id)}
              aria-expanded={activeTab === t.id}
            >
              <Icon name={t.icon} />
              {t.label}
              {t.id === 'layers' && layers.length > 0 && <span className="tab-badge">{layers.length}</span>}
            </button>
          ))}
          </div>
          <div className="workspace-context" title={layers[0]?.filename ?? 'No FITS loaded'}>
            <span>{layers[0]?.station ?? 'No observation loaded'}</span>
            {layers[0] && <small>{layers[0].date} · {layers[0].filename}</small>}
          </div>
        </div>

        {activeTab && <>
          <button className="workspace-drawer-scrim" aria-label={`Close ${PANEL_TITLES[activeTab]}`} onClick={() => setActiveTab(null)} />
          <aside className="workspace-drawer" aria-label={`${PANEL_TITLES[activeTab]} controls`}>
            <header className="workspace-drawer-header">
              <div><span className="section-kicker">Spectrogram controls</span><h2>{PANEL_TITLES[activeTab]}</h2></div>
              <button type="button" className="drawer-close" onClick={() => setActiveTab(null)} autoFocus>Close</button>
            </header>
            <div className="workspace-drawer-body">{renderTabPanel()}</div>
          </aside>
        </>}

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
          theme={theme}
        />
        {currentLightCurve && (
          <LightCurveResult
            result={currentLightCurve}
            theme={theme}
            timeRange={primaryTimeRange}
            onClose={() => setLightCurveResult(null)}
          />
        )}
        {taskStatus?.status === 'succeeded' && taskStatus.type === 'combine_time' && taskStatus.result?.artifact_url && (
          <CombinedSpectrogram key={taskStatus.id} artifactUrl={taskStatus.result.artifact_url} theme={theme} />
        )}
        {taskStatus?.status === 'succeeded' && taskStatus.type === 'spectral_overview' && taskStatus.result?.artifact_url && <DailyOverview key={taskStatus.id} artifactUrl={taskStatus.result.artifact_url} theme={theme} />}
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
