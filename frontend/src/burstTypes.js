// Burst types returned by /api/burst/detect, with the colour used for their boxes.
export const BURST_TYPES = {
  type2: { label: 'II', color: '#fb923c' },
  type3: { label: 'III', color: '#22d3ee' },
  type3s: { label: 'IIIs', color: '#c084fc' },
  type4: { label: 'IV', color: '#f472b6' },
  type5: { label: 'V', color: '#a3e635' },
};

export const burstStyle = (type) => BURST_TYPES[type] ?? { label: type, color: '#fbbf24' };

export function describeDetections(result) {
  if (!result?.available) {
    return { status: 'unavailable', label: 'Unavailable', detail: result?.reason || 'Detector unavailable.' };
  }
  const count = result.detections?.length ?? 0;
  if (!count) {
    return {
      status: 'clear',
      label: 'No bursts detected',
      detail: `No box reached the model confidence threshold (${result.threshold}).`,
    };
  }
  const experimental = result.detections.some((d) => d.experimental);
  return {
    status: 'burst',
    label: `${count} burst${count === 1 ? '' : 's'} detected`,
    detail: experimental ? 'Types IV and V are experimental: few training examples.' : '',
  };
}
