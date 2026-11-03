// File times are archive timestamps, not necessarily exact quarter-hours.
// Only selector labels use a nominal slot; scientific UTC axes stay untouched.
const BLOCK_SECONDS = 15 * 60;
const CLOCK_TOLERANCE_SECONDS = 2;
const FILE_RE = /^(?<station>.+)_(?<date>\d{8})_(?<time>\d{6})(?:_(?<focus>[A-Za-z0-9-]+))?\.fits?(?:\.gz)?$/i;

function seconds(time) {
  if (!/^\d{2}:\d{2}:\d{2}$/.test(time)) return null;
  const [h, m, s] = time.split(':').map(Number);
  return h < 24 && m < 60 && s < 60 ? h * 3600 + m * 60 + s : null;
}

export function displayBlockTime(time) {
  const value = seconds(time);
  if (value === null) return { time, approximate: false, dayOffset: 0 };
  const nominal = Math.round(value / BLOCK_SECONDS) * BLOCK_SECONDS;
  const rounded = Math.abs(nominal - value) <= CLOCK_TOLERANCE_SECONDS ? nominal : value;
  const clock = rounded % 86400;
  const part = (n) => String(n).padStart(2, '0');
  return {
    time: `${part(Math.floor(clock / 3600))}:${part(Math.floor(clock / 60) % 60)}:${part(clock % 60)}`,
    approximate: rounded !== value,
    dayOffset: Math.floor(rounded / 86400),
  };
}

export function selectCombineBlocks(files, selectedFilename, limit = 4) {
  const selected = files.find((file) => file.filename === selectedFilename);
  const context = selected?.filename.match(FILE_RE)?.groups;
  if (!context) return { filenames: [], focusCode: null, notice: 'Select a FITS block first.' };
  const focusCode = context.focus ?? null;
  const candidates = files.filter((file) => {
    const info = file.filename.match(FILE_RE)?.groups;
    return info && info.station === context.station && info.date === context.date
      && (info.focus ?? null) === focusCode && info.time >= context.time;
  }).sort((a, b) => a.filename.localeCompare(b.filename));
  const picked = [];
  const seen = new Set();
  let previous = null;
  let notice = '';
  for (let file of candidates) {
    const stamp = file.filename.match(FILE_RE).groups.time;
    if (seen.has(stamp)) continue; // .fit/.fits/.gz copies are one observation
    seen.add(stamp);
    if (stamp === context.time) file = selected;
    const start = seconds(`${stamp.slice(0, 2)}:${stamp.slice(2, 4)}:${stamp.slice(4, 6)}`);
    if (start === null) break;
    // Stop only at a clear gap. A block that starts early may still continue
    // the previous one; the server checks the real sample times and rejects
    // true overlaps.
    if (previous !== null && start - previous - BLOCK_SECONDS > CLOCK_TOLERANCE_SECONDS) {
      notice = 'Selection stops at a gap; use Spectral overview for irregular intervals.';
      break;
    }
    picked.push(file.filename);
    previous = start;
    if (picked.length === limit) break;
  }
  if (!notice && picked.length < limit) {
    notice = `Only ${picked.length} consecutive block${picked.length === 1 ? '' : 's'} available from this starting point for this receiver today.`;
  }
  return { filenames: picked, focusCode, notice };
}

// Neighbouring block of the same receiver that can be joined with `filename`
// (direction 'previous' | 'next'); the server still checks the real sample times.
export function adjacentBlock(files, filename, direction) {
  const selected = filename.match(FILE_RE)?.groups;
  if (!selected) return null;
  const clock = (time) => seconds(`${time.slice(0, 2)}:${time.slice(2, 4)}:${time.slice(4, 6)}`);
  const origin = clock(selected.time);
  const sign = direction === 'next' ? 1 : -1;
  let best = null;
  for (const file of files) {
    const info = file.filename.match(FILE_RE)?.groups;
    if (!info || info.station !== selected.station || info.date !== selected.date
      || (info.focus ?? null) !== (selected.focus ?? null)) continue;
    const gap = sign * (clock(info.time) - origin);
    if (gap > 0 && gap <= BLOCK_SECONDS + CLOCK_TOLERANCE_SECONDS && (!best || gap < best.gap)) {
      best = { gap, filename: file.filename };
    }
  }
  return best?.filename ?? null;
}

// Joined observations: a layer response lists the blocks it was built from.
export function blockFilenames(source) {
  return source?.filenames?.length > 1 ? source.filenames : undefined;
}

export function addBlockParams(params, source) {
  blockFilenames(source)?.forEach((name) => params.append('filenames', name));
  return params;
}

// Stable identity of what a layer shows (single block or joined pair).
export const layerKey = (layer) => (
  `${layer.station}:${layer.date}:${blockFilenames(layer)?.join('+') ?? layer.filename}`
);
