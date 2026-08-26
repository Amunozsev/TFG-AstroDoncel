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

  const target = new Date(pendingEvent.startedAt);
  const targetSeconds = target.getUTCHours() * 3600 + target.getUTCMinutes() * 60 + target.getUTCSeconds();
  const ordered = [...files].sort((a, b) => secondsOfDay(a.time) - secondsOfDay(b.time));
  return [...ordered].reverse().find((item) => secondsOfDay(item.time) <= targetSeconds) ?? ordered[0];
}
