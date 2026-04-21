import { useState, useEffect } from 'react';
import Plotly from 'plotly.js-dist';
import _factory from 'react-plotly.js/factory';

const Plot = (_factory.default ?? _factory)(Plotly);

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
          type: 'heatmap',
          x: datos.tiempos,
          y: datos.frecuencias,
          z: datos.datos,
          colorscale: 'Jet',
          zmin: 0,
          zmax: 20,
        },
      ]}
      layout={{
        title: { text: 'Espectrograma Solar e-Callisto' },
        xaxis: { title: 'Tiempo (s)' },
        yaxis: { autorange: 'reversed', title: 'Frecuencia (MHz)' },
        autosize: true,
      }}
      useResizeHandler
      style={{ width: '100%', height: '100%' }}
    />
  );
}
