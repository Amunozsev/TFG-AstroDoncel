const FITS_PROVENANCE_FIELDS = [
  'DATE-OBS', 'TIME-OBS', 'INSTRUME', 'CONTENT', 'ORIGIN', 'OBSERVAT',
  'OBS_LAT', 'OBS_LON', 'OBS_LAC', 'OBS_LOC', 'BUNIT',
];

function selectedHeaderFields(header = {}) {
  return Object.fromEntries(
    FITS_PROVENANCE_FIELDS
      .filter((key) => header[key] !== undefined)
      .map((key) => [key, header[key]]),
  );
}

export function buildAnalysisManifest({
  date,
  station,
  layers,
  processing,
  display,
  solarContext,
  generatedAt = new Date().toISOString(),
}) {
  return {
    schema: 'astrodoncel.analysis-manifest.v1',
    generated_at: generatedAt,
    application: { name: 'AstroDoncel', version: '0.4.0' },
    selection: {
      date_utc: date,
      primary_station: station,
      layers: layers.map((layer) => ({
        station: layer.station,
        date_utc: layer.date,
        filename: layer.filename,
        intensity_unit: layer.intensity_unit,
        frequency_unit: 'MHz',
        time_standard: 'UTC',
        fits_provenance: selectedHeaderFields(layer.fits_header),
      })),
    },
    processing,
    display,
    solar_context: solarContext,
    catalogue: { id: 'dearce_v3', label: 'deARCE (v3)' },
    interpretation: {
      measured: ['FITS time axis', 'FITS frequency axis', 'instrumental intensity'],
      inferred: ['CNN+MIL candidate probability'],
      heuristic: ['visual candidate localization', 'Xmatch nominal block interval'],
      experimental: ['Type II band-splitting output'],
    },
    provenance: [
      'e-CALLISTO/ETHZ archive data',
      'AstroDoncel/Universidad de Alcalá portal and deARCE (v3) catalogue',
      'Sahan S. Liyanage e-CALLISTO FITS Analyzer and Burst_No_Burst reference methods',
    ],
  };
}

export function downloadManifest(manifest) {
  const blob = new Blob([`${JSON.stringify(manifest, null, 2)}\n`], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  const station = manifest.selection.primary_station ?? 'selection';
  link.href = url;
  link.download = `astrodoncel-${station}-${manifest.selection.date_utc}.analysis.json`;
  link.click();
  URL.revokeObjectURL(url);
}
