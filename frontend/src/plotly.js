import Plotly from 'plotly.js/lib/core';
import Heatmap from 'plotly.js/lib/heatmap';
import Scatter from 'plotly.js/lib/scatter';
import ScatterGeo from 'plotly.js/lib/scattergeo';
import _factory from 'react-plotly.js/factory';

Plotly.register([Heatmap, Scatter, ScatterGeo]);

const createPlotlyComponent = _factory.default ?? _factory;

export const Plot = createPlotlyComponent(Plotly);
export default Plotly;
