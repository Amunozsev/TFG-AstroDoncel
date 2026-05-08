import { useState } from 'react';
import Spectrogram from './Spectrogram';
import './App.css';

const today = new Date().toISOString().slice(0, 10);

const STATIONS = [
  'PHOENIX',
  'SPAIN-SIGUENZA',
  'SPAIN-PERALEJOS',
  'ALASKA-HAARP',
  'PERU-ICA',
  'AUSTRIA-GRAZ',
  'SWISS-LANDSCHLACHT',
  'BIR',
  'MAURITIUS',
  'SSRT',
];

export default function App() {
  const [station, setStation]           = useState('PHOENIX');
  const [date, setDate]                 = useState('1989-03-13');
  const [useSahanFilter, setSahan]      = useState(false);
  const [showGoes, setShowGoes]         = useState(false);
  const [zmin, setZmin]                 = useState(-5);
  const [zmax, setZmax]                 = useState(30);
  const [useCustomZ, setUseCustomZ]     = useState(false);
  // triggerLoad=1 → carga automática al abrir
  const [triggerLoad, setTriggerLoad]   = useState(1);

  function handleLoad() {
    setTriggerLoad((n) => n + 1);
  }

  // Callback desde Spectrogram: inicializa los sliders con los percentiles del servidor
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
            <select
              className="control-input"
              value={station}
              onChange={(e) => setStation(e.target.value)}
            >
              {STATIONS.map((s) => (
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

        <div className="sidebar-section">
          <h2 className="section-title">Procesamiento</h2>

          <label className="control-checkbox">
            <input
              type="checkbox"
              checked={useSahanFilter}
              onChange={(e) => setSahan(e.target.checked)}
            />
            Filtro de ruido (Sahan RFI)
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
              onChange={(e) => {
                setUseCustomZ(e.target.checked);
              }}
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
          <button className="btn-load" onClick={handleLoad}>
            ▶ Cargar espectrograma
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
