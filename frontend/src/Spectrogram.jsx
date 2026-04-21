import { useState, useEffect } from 'react';
import Plot from 'react-plotly.js';

export default function Spectrogram() {
  const [datos, setDatos] = useState(null);

  useEffect(() => {
    fetch('/datos_prueba.json')
      .then((res) => res.json())
      .then(setDatos);
  }, []);

  if (!datos) return <p>Cargando datos astronómicos...</p>;

  return (
    <Plot
      data={[
        {
          type: 'heatmapgl',
          x: datos.tiempos,
          y: datos.frecuencias,
          z: datos.datos,
          colorscale: 'Jet',
        },
      ]}
      layout={{
        title: { text: 'Espectrograma Solar e-Callisto' },
        xaxis: { title: 'Tiempo (s)' },
        yaxis: { title: 'Frecuencia (MHz)' },
        autosize: true,
      }}
      useResizeHandler
      style={{ width: '100%', height: '100%' }}
    />
  );
}
