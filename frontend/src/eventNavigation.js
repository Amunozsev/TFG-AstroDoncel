function secondsOfDay(value) {
  return value.split(':').reduce(
    (sum, part, index) => sum + Number(part) * [3600, 60, 1][index],
    0,
  );
}

export function fileForEvent(files, filesContext, pendingEvent) {
  if (
    !pendingEvent
    || filesContext?.station !== pendingEvent.station
    || filesContext?.date !== pendingEvent.date
    || files.length === 0
  ) return null;

  if (pendingEvent.filename) {
    const exact = files.find((item) => item.filename === pendingEvent.filename);
    if (exact) return exact;
    return null;
  }

  const target = new Date(pendingEvent.startedAt);
  const targetSeconds = target.getUTCHours() * 3600 + target.getUTCMinutes() * 60 + target.getUTCSeconds();
  const candidates = pendingEvent.focusCode
    ? files.filter((item) => item.focus_code === pendingEvent.focusCode)
    : files;
  const ordered = [...candidates].sort((a, b) => secondsOfDay(a.time) - secondsOfDay(b.time));
  if (ordered.length === 0) return null;
  return [...ordered].reverse().find((item) => secondsOfDay(item.time) <= targetSeconds) ?? ordered[0];
}
