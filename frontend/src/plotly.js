import Plotly from 'plotly.js/lib/core';
import Heatmap from 'plotly.js/lib/heatmap';
import Scatter from 'plotly.js/lib/scatter';
import ScatterGeo from 'plotly.js/lib/scattergeo';

Plotly.register([Heatmap, Scatter, ScatterGeo]);

export default Plotly;
