const STATION_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;
const FITS_RE = /^[A-Za-z0-9][A-Za-z0-9_-]*_\d{8}_\d{6}(?:_[A-Za-z0-9-]+)?\.fits?(?:\.gz)?$/i;

function parameter(params, canonical, legacy) {
  const current = params.get(canonical);
  const old = params.get(legacy);
  if (current && old && current !== old) {
    throw new Error(`Conflicting ${canonical} parameters in the link.`);
  }
  return current ?? old;
}

function validIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function observationDateRange(value, period = 'day') {
  const start = period === 'month' && value ? `${value.slice(0, 7)}-01` : value;
  if (!validIsoDate(start)) return null;
  const parsed = new Date(`${start}T00:00:00Z`);
  if (period === 'month') parsed.setUTCMonth(parsed.getUTCMonth() + 1);
  else parsed.setUTCDate(parsed.getUTCDate() + 1);
  return { start, end: parsed.toISOString().slice(0, 10) };
}

export function parseObservationSearch(search) {
  const params = new URLSearchParams(search);
  let station;
  let date;
  let filename;
  try {
    station = parameter(params, 'station', 'estacion');
    date = parameter(params, 'date', 'fecha');
    filename = parameter(params, 'filename', 'archivo');
  } catch (cause) {
    return { observation: null, error: cause.message };
  }
  if (!station && !date && !filename) return { observation: null, error: null };
  if (!station || !date || !filename) {
    return { observation: null, error: 'The observation link must include station, date and filename.' };
  }
  if (!STATION_RE.test(station)) {
    return { observation: null, error: 'The observation link contains an invalid station.' };
  }
  if (!validIsoDate(date)) {
    return { observation: null, error: 'The observation link contains an invalid date.' };
  }
  if (!FITS_RE.test(filename)) {
    return { observation: null, error: 'The observation link contains an invalid FITS filename.' };
  }
  const context = filename.match(/^(?<station>.+)_(?<date>\d{8})_(?<time>\d{6})(?:_(?<focus>[A-Za-z0-9-]+))?\.fits?(?:\.gz)?$/i);
  if (
    !context
    || context.groups.station.toUpperCase() !== station.toUpperCase()
    || context.groups.date !== date.replaceAll('-', '')
  ) {
    return { observation: null, error: 'The FITS filename does not belong to the requested station and date.' };
  }
  const timestamp = `${date}T${context.groups.time.slice(0, 2)}:${context.groups.time.slice(2, 4)}:${context.groups.time.slice(4, 6)}Z`;
  const instant = new Date(timestamp);
  if (!Number.isFinite(instant.getTime()) || instant.toISOString() !== timestamp.replace('Z', '.000Z')) {
    return { observation: null, error: 'The FITS filename contains an invalid observation time.' };
  }
  return {
    observation: {
      station,
      date,
      filename,
      focusCode: context.groups.focus ?? null,
      startedAt: timestamp,
    },
    error: null,
  };
}

export function observationPath(observation, location = window.location) {
  const params = new URLSearchParams();
  params.set('station', observation.station);
  params.set('date', observation.date);
  params.set('filename', observation.filename);
  return `${location.pathname}?${params}${location.hash ?? ''}`;
}

export function writeObservationUrl(observation, { replace = false } = {}) {
  const path = observationPath(observation);
  if (!replace && path === `${window.location.pathname}${window.location.search}${window.location.hash}`) {
    return path;
  }
  window.history[replace ? 'replaceState' : 'pushState']({}, '', path);
  return path;
}
