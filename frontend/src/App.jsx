import { useState, useEffect, useCallback } from 'react';
import Spectrogram from './Spectrogram';
import './App.css';

const API_BASE = 'http://localhost:8000';

const FALLBACK_STATIONS = [
  'ALASKA-HAARP', 'AUSTRIA-UNIGRAZ', 'BIR', 'HUMAIN', 'LEARMONTH',
  'MAURITIUS', 'PERU-ICA', 'PHOENIX', 'SPAIN-PERALEJOS', 'SPAIN-SIGUENZA',
  'SSRT', 'SWISS-LANDSCHLACHT',
];

export default function App() {
  const [stations, setStations]             = useState(FALLBACK_STATIONS);
  const [stationsSource, setStationsSource] = useState('');
  // Primary station: drives the burst-file list
  const [station, setStation]               = useState('SPAIN-SIGUENZA');
  // All stations selected for multi-layer loading
  const [selectedStations, setSelectedStations] = useState(['SPAIN-SIGUENZA']);
  const [date, setDate]                     = useState(() => new Date().toISOString().slice(0, 10));

  // Daily burst list (primary station only)
  const [files, setFiles]                   = useState([]);
  const [filesLoading, setFilesLoading]     = useState(false);
  const [selectedFile, setSelectedFile]     = useState(null);

  const [useSahanFilter, setSahan]          = useState(false);
  const [showGoes, setShowGoes]             = useState(false);
  const [colormap, setColormap]             = useState('observatory');
  const [zmin, setZmin]                     = useState(-5);
  const [zmax, setZmax]                     = useState(30);
  const [useCustomZ, setUseCustomZ]         = useState(false);
  const [triggerLoad, setTriggerLoad]       = useState(0);
  const [hasLoaded, setHasLoaded]           = useState(false);

  // Fetched layer data (owned here, passed down to Spectrogram)
  const [layers, setLayers]                 = useState([]);
  const [failedStations, setFailedStations] = useState([]);
  const [fetchLoading, setFetchLoading]     = useState(false);
  const [fetchError, setFetchError]         = useState(null);

  // Per-layer UI state: { [station]: { visible: bool, opacity: number } }
  const [layerState, setLayerState]         = useState({});

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
          if (!data.stations.includes(station)) {
            setStation(data.stations[0]);
            setSelectedStations([data.stations[0]]);
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
    setFilesLoading(true);
    setFiles([]);
    setSelectedFile(null);
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

    async function fetchLayers() {
      setFetchLoading(true);
      setFetchError(null);
      try {
        let newLayers;
        let newFailed = [];

        if (selectedStations.length > 1) {
          const params = new URLSearchParams({
            date,
            sahan_filter: String(useSahanFilter),
            max_time_bins: '1500',
          });
          if (selectedFile) params.set('filename', selectedFile);
          selectedStations.forEach((s) => params.append('stations', s));
          const res = await fetch(`${API_BASE}/api/spectrogram/combine?${params}`);
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail ?? `Error ${res.status}`);
          }
          const data = await res.json();
          newLayers = data.layers;
          newFailed = data.failed ?? [];
        } else {
          let url =
            `${API_BASE}/api/spectrogram` +
            `?station=${encodeURIComponent(selectedStations[0] ?? station)}` +
            `&date=${encodeURIComponent(date)}` +
            `&sahan_filter=${useSahanFilter}` +
            `&max_time_bins=1500`;
          if (selectedFile) url += `&filename=${encodeURIComponent(selectedFile)}`;
          const res = await fetch(url);
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

  // Chip click only appears in single-station mode (burst list is hidden otherwise)
  function handleChipClick(filename) {
    setSelectedFile(filename);
    setHasLoaded(true);
    setTriggerLoad((n) => n + 1);
  }

  function toggleStation(s) {
    if (selectedStations.includes(s)) {
      if (selectedStations.length === 1) return; // always keep at least one selected
      const next = selectedStations.filter((x) => x !== s);
      setSelectedStations(next);
      if (station === s) setStation(next[0]); // keep primary valid after removal
    } else {
      setSelectedStations([...selectedStations, s]);
      setStation(s); // newly added station becomes primary for file list
    }
  }

  function setLayerVisible(st, visible) {
    setLayerState((prev) => ({ ...prev, [st]: { ...prev[st], visible } }));
  }

  function setLayerOpacity(st, opacity) {
    setLayerState((prev) => ({ ...prev, [st]: { ...prev[st], opacity } }));
  }

  const loadDisabled =
    !date ||
    selectedStations.length === 0 ||
    (files.length > 0 && !selectedFile);

  return (
    <div className="dashboard">

      {/* ── Sidebar ── */}
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
            {selectedStations.length > 1 && (
              <span style={{ fontSize: '0.65rem', color: '#38bdf8', marginLeft: '0.3rem' }}>
                {selectedStations.length} selected
              </span>
            )}
            <div className="station-checklist">
              {stations.map((s) => (
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

            {filesLoading && <p className="files-hint">Querying ETHZ…</p>}
            {!filesLoading && files.length === 0 && <p className="files-hint">No files available.</p>}

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
                  .map(([hour, bursts]) => (
                    <div key={hour} className="burst-hour-group">
                      <div className="burst-hour-header">{hour}:xx UTC</div>
                      {bursts.map((f) => {
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
                  ))}
              </div>
            )}
        </div>

        <div className="sidebar-section">
          <h2 className="section-title">Processing</h2>

          <label className="control-checkbox">
            <input
              type="checkbox"
              checked={useSahanFilter}
              onChange={(e) => setSahan(e.target.checked)}
            />
            Full RFI filter (Sahan)
          </label>

          <label className="control-checkbox">
            <input
              type="checkbox"
              checked={showGoes}
              onChange={(e) => setShowGoes(e.target.checked)}
            />
            Overlay GOES/XRS data
          </label>

          <label className="control-label" style={{ marginTop: '0.5rem' }}>
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
        </div>

        {/* ── Layer controls (shown after first successful load) ────────────── */}
        {hasLoaded && (layers.length > 0 || failedStations.length > 0) && (
          <div className="sidebar-section">
            <h2 className="section-title">Layers</h2>
            {layers.map((layer) => {
              const ls = layerState[layer.station] ?? { visible: true, opacity: 1 };
              return (
                <div key={layer.station} className="layer-row">
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
        )}

        <div className="sidebar-section">
          <h2 className="section-title">Contrast</h2>

          <label className="control-checkbox" style={{ marginBottom: '0.5rem' }}>
            <input
              type="checkbox"
              checked={useCustomZ}
              onChange={(e) => setUseCustomZ(e.target.checked)}
            />
            Manual adjustment
          </label>

          <label className="control-label">
            <span className="slider-row">
              <span>Z min</span>
              <span className="slider-value">{zmin}</span>
            </span>
            <input
              type="range"
              className="control-slider"
              min="-100" max="50" step="0.5"
              value={zmin}
              disabled={!useCustomZ}
              onChange={(e) => { setUseCustomZ(true); setZmin(parseFloat(e.target.value)); }}
            />
          </label>

          <label className="control-label">
            <span className="slider-row">
              <span>Z max</span>
              <span className="slider-value">{zmax}</span>
            </span>
            <input
              type="range"
              className="control-slider"
              min="-50" max="300" step="0.5"
              value={zmax}
              disabled={!useCustomZ}
              onChange={(e) => { setUseCustomZ(true); setZmax(parseFloat(e.target.value)); }}
            />
          </label>
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
        />
      </main>

    </div>
  );
}
