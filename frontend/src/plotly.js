import Plotly from 'plotly.js/lib/core';
import Heatmap from 'plotly.js/lib/heatmap';
import Scatter from 'plotly.js/lib/scatter';
import ScatterGeo from 'plotly.js/lib/scattergeo';
import _factory from 'react-plotly.js/factory';

Plotly.register([Heatmap, Scatter, ScatterGeo]);

// Shared e-CALLISTO palette: preserve identical intensities across the viewers.
export const OBSERVATORY_COLOR_SCALE = [
  [0.00, '#000000'], [0.10, '#0a0038'], [0.20, '#1a0080'],
  [0.30, '#4a0090'], [0.40, '#7a0080'], [0.50, '#aa2050'],
  [0.60, '#cc0000'], [0.70, '#e06000'], [0.80, '#f5a000'],
  [0.90, '#ffcc00'], [1.00, '#ffffb0'],
];

const createPlotlyComponent = _factory.default ?? _factory;

export const Plot = createPlotlyComponent(Plotly);
export default Plotly;
