import { useState, useEffect } from 'react';
import Spectrogram from './Spectrogram';
import './App.css';

const API_BASE = 'http://localhost:8000';

// Lista de respaldo para renderizado inicial antes de que la API responda
const FALLBACK_STATIONS = [
  'ALASKA-HAARP', 'AUSTRIA-GRAZ', 'BIR', 'LEARMONTH', 'MAURITIUS',
  'PERU-ICA', 'PHOENIX', 'SPAIN-PERALEJOS', 'SPAIN-SIGUENZA',
  'SSRT', 'SWISS-LANDSCHLACHT',
];

export default function App() {
  const [stations, setStations]           = useState(FALLBACK_STATIONS);
  const [stationsSource, setStationsSource] = useState('');
  const [station, setStation]             = useState('PHOENIX');
  const [date, setDate]                   = useState('1989-03-13');
  const [useSahanFilter, setSahan]        = useState(false);
  const [showGoes, setShowGoes]           = useState(false);
  const [zmin, setZmin]                   = useState(-5);
  const [zmax, setZmax]                   = useState(30);
  const [useCustomZ, setUseCustomZ]       = useState(false);
  // triggerLoad=1 → carga automática al montar; incrementar para forzar recarga manual
  const [triggerLoad, setTriggerLoad]     = useState(1);

  // Carga la lista real de estaciones desde la API al montar el componente
  useEffect(() => {
    async function loadStations() {
      try {
        const res = await fetch(`${API_BASE}/api/stations`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.stations && data.stations.length > 0) {
          setStations(data.stations);
          setStationsSource(data.source);
          // Si la estación seleccionada no está en la lista real, selecciona la primera
          if (!data.stations.includes(station)) {
            setStation(data.stations[0]);
          }
        }
      } catch (err) {
        console.warn('Lista de estaciones desde API falló, usando respaldo:', err.message);
        setStationsSource('static');
      }
    }
    loadStations();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleLoad() {
    setTriggerLoad((n) => n + 1);
  }

  // Callback desde Spectrogram: inicializa los sliders con vmin/vmax del servidor
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
                title={stationsSource === 'ethz' ? 'Lista obtenida del archivo ETHZ en tiempo real' : 'Lista estática de respaldo'}
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
          <button className="btn-load" onClick={handleLoad}>
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
