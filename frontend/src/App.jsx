import { useState } from 'react';
import Spectrogram from './Spectrogram';
import './App.css';

const today = new Date().toISOString().slice(0, 10);

export default function App() {
  const [station, setStation] = useState('PHOENIX');
  const [date, setDate] = useState(today);
  const [useSahanFilter, setUseSahanFilter] = useState(false);
  // triggerLoad empieza en 1 para que el gráfico cargue automáticamente al abrir
  const [triggerLoad, setTriggerLoad] = useState(1);

  return (
    <div className="dashboard">

      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>e-CALLISTO<br /><span>Spain</span></h1>
          <p className="sidebar-subtitle">Portal de Espectrogramas Solares</p>
        </div>

        <div className="sidebar-section">
          <h2 className="section-title">Controles</h2>

          <label className="control-label">
            Estación
            <input
              type="text"
              className="control-input"
              value={station}
              onChange={(e) => setStation(e.target.value)}
            />
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

          <label className="control-checkbox">
            <input
              type="checkbox"
              checked={useSahanFilter}
              onChange={(e) => setUseSahanFilter(e.target.checked)}
            />
            Aplicar filtro de ruido (Sahan)
          </label>

          <button
            className="btn-load"
            onClick={() => setTriggerLoad((n) => n + 1)}
          >
            Cargar espectrograma
          </button>
        </div>

        <div className="sidebar-status">
          <span className="status-dot" />
          Backend conectado · puerto 8000
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
          triggerLoad={triggerLoad}
        />
      </main>

    </div>
  );
}
