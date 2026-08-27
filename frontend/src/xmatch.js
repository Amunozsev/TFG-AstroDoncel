function timestamp(value) {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function blockForEvent(blocks, event) {
  const eventTime = timestamp(event?.started_at);
  if (eventTime === null) return null;

  return [...(blocks ?? [])]
    .filter((block) => {
      const start = timestamp(block.start_at);
      const end = timestamp(block.end_at);
      return start !== null && end !== null && start <= eventTime && eventTime < end;
    })
    .sort((left, right) => timestamp(right.start_at) - timestamp(left.start_at))[0] ?? null;
}

export function expandXmatchRows(stationRows, filter = 'all') {
  const displayRows = [];

  for (const stationRow of stationRows ?? []) {
    const receivers = stationRow.receivers ?? [];
    if (receivers.length === 0) {
      displayRows.push({
        key: stationRow.station,
        label: stationRow.station,
        station: stationRow.station,
        focusCode: null,
        availability: stationRow.availability ?? [],
        eventPoints: (stationRow.events ?? []).map((event) => ({
          label: stationRow.station,
          station: stationRow.station,
          focusCode: null,
          filename: null,
          event,
        })),
      });
      continue;
    }

    const matchedEvents = new Set();
    for (const receiver of receivers) {
      const eventPoints = (stationRow.events ?? []).flatMap((event) => {
        const block = blockForEvent(receiver.blocks, event);
        if (!block) return [];
        matchedEvents.add(event);
        return [{
          label: `${stationRow.station} · FC ${receiver.focus_code}`,
          station: stationRow.station,
          focusCode: receiver.focus_code,
          filename: block.filename,
          event,
        }];
      });
      displayRows.push({
        key: `${stationRow.station}::${receiver.focus_code}`,
        label: `${stationRow.station} · FC ${receiver.focus_code}`,
        station: stationRow.station,
        focusCode: receiver.focus_code,
        availability: receiver.availability ?? [],
        eventPoints,
      });
    }

    const unmatched = (stationRow.events ?? []).filter((event) => !matchedEvents.has(event));
    if (unmatched.length > 0) {
      displayRows.push({
        key: `${stationRow.station}::unmatched`,
        label: `${stationRow.station} · no matching FC`,
        station: stationRow.station,
        focusCode: null,
        availability: [],
        eventPoints: unmatched.map((event) => ({
          label: `${stationRow.station} · no matching FC`,
          station: stationRow.station,
          focusCode: null,
          filename: null,
          event,
        })),
      });
    }
  }

  return filter === 'positive'
    ? displayRows.filter((row) => row.eventPoints.length > 0)
    : displayRows;
}
