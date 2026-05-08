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
  const [station, setStation]               = useState('SPAIN-SIGUENZA');
  const [date, setDate]                     = useState('2024-05-08');

  // Lista de bursts del día
  const [files, setFiles]                   = useState([]);
  const [filesLoading, setFilesLoading]     = useState(false);
  const [selectedFile, setSelectedFile]     = useState(null);

  const [useSahanFilter, setSahan]          = useState(false);
  const [showGoes, setShowGoes]             = useState(false);
  const [zmin, setZmin]                     = useState(-5);
  const [zmax, setZmax]                     = useState(30);
  const [useCustomZ, setUseCustomZ]         = useState(false);
  const [triggerLoad, setTriggerLoad]       = useState(1);

  // ── Carga lista real de estaciones ──────────────────────────────────────────
  useEffect(() => {
    async function loadStations() {
      try {
        const res = await fetch(`${API_BASE}/api/stations`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.stations?.length > 0) {
          setStations(data.stations);
          setStationsSource(data.source);
          if (!data.stations.includes(station)) setStation(data.stations[0]);
        }
      } catch (err) {
        console.warn('Estaciones desde API fallaron, usando respaldo:', err.message);
        setStationsSource('static');
      }
    }
    loadStations();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Carga lista de bursts cuando cambian estación o fecha ──────────────────
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
      console.warn('No se pudo cargar lista de bursts:', err.message);
    } finally {
      setFilesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFiles(station, date);
  }, [station, date, loadFiles]);

  function handleLoad() {
    setTriggerLoad((n) => n + 1);
  }

  function handleDataLoaded(vmin, vmax) {
    if (!useCustomZ) {
      setZmin(Math.round(vmin * 10) / 10);
      setZmax(Math.round(vmax * 10) / 10);
    }
  }

  return (
    <div className="dashboard">

      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>e-CALLISTO<br /><span>Spain</span></h1>
          <p className="sidebar-subtitle">Portal de Espectrogramas Solares</p>
        </div>

        <div className="sidebar-section">
          <h2 className="section-title">Observación</h2>

          <label className="control-label">
            Estación
            {stationsSource && (
              <span
                title={stationsSource === 'ethz' ? 'Lista obtenida de ETHZ en tiempo real' : 'Lista estática de respaldo'}
                style={{ marginLeft: '0.4rem', fontSize: '0.65rem', color: stationsSource === 'ethz' ? '#38bdf8' : '#f59e0b', verticalAlign: 'middle' }}
              >
                {stationsSource === 'ethz' ? '● ETHZ' : '● local'}
              </span>
            )}
            <select
              className="control-input"
              value={station}
              onChange={(e) => setStation(e.target.value)}
            >
              {stations.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>

          <label className="control-label">
            Fecha
            <input
              type="date"
              className="control-input"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
        </div>

        {/* ── Lista de bursts ─────────────────────────────────────────────── */}
        <div className="sidebar-section burst-section">
          <h2 className="section-title">
            Burst / Archivo
            {filesLoading && <span className="files-loading-dot" />}
            {!filesLoading && files.length > 0 && (
              <span style={{ color: '#4a7a9b', fontWeight: 400, marginLeft: '0.3rem' }}>
                ({files.length})
              </span>
            )}
          </h2>

          {filesLoading && (
            <p className="files-hint">Consultando ETHZ…</p>
          )}

          {!filesLoading && files.length === 0 && (
            <p className="files-hint">No hay archivos disponibles.</p>
          )}

          {!filesLoading && files.length > 0 && (
            <div className="burst-list">
              {files.map((f) => (
                <button
                  key={f.filename}
                  className={`burst-chip ${selectedFile === f.filename ? 'active' : ''}`}
                  onClick={() => setSelectedFile(f.filename)}
                  title={f.filename}
                >
                  {f.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="sidebar-section">
          <h2 className="section-title">Procesamiento</h2>

          <label className="control-checkbox">
            <input
              type="checkbox"
              checked={useSahanFilter}
              onChange={(e) => setSahan(e.target.checked)}
            />
            Filtro RFI completo (Sahan)
          </label>

          <label className="control-checkbox">
            <input
              type="checkbox"
              checked={showGoes}
              onChange={(e) => setShowGoes(e.target.checked)}
            />
            Superponer datos GOES/XRS
          </label>
        </div>

        <div className="sidebar-section">
          <h2 className="section-title">Contraste</h2>

          <label className="control-checkbox" style={{ marginBottom: '0.5rem' }}>
            <input
              type="checkbox"
              checked={useCustomZ}
              onChange={(e) => setUseCustomZ(e.target.checked)}
            />
            Ajuste manual
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
            disabled={!selectedFile && files.length > 0}
          >
            ▶ Recargar
          </button>
        </div>

        <div className="sidebar-status">
          <span className="status-dot" />
          Backend · puerto 8000
        </div>

        <div className="sidebar-footer">
          <div>TFG — UAH · 2026</div>
          <div>Alfonso Muñoz Sevillano</div>
        </div>
      </aside>

      {/* ── Área central ── */}
      <main className="main-content">
        <Spectrogram
          station={station}
          date={date}
          filename={selectedFile}
          useSahanFilter={useSahanFilter}
          showGoes={showGoes}
          zmin={useCustomZ ? zmin : null}
          zmax={useCustomZ ? zmax : null}
          triggerLoad={triggerLoad}
          onDataLoaded={handleDataLoaded}
        />
      </main>

    </div>
  );
}
