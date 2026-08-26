export function describeBurstResult(result) {
  if (!result?.available) {
    return { status: 'unavailable', label: 'Unavailable', detail: result?.reason || 'Detector unavailable.' };
  }
  if (result.is_burst) {
    return {
      status: 'burst',
      label: 'Burst detected',
      detail: result.events?.length
        ? `${result.events.length} time-frequency interval${result.events.length === 1 ? '' : 's'} localized.`
        : 'The file classifier is positive, but no reliable time-frequency interval was localized.',
    };
  }
  if (result.is_candidate || result.file_score >= result.candidate_threshold) {
    return {
      status: 'candidate',
      label: 'Candidate',
      detail: result.events?.length
        ? `${result.events.length} interval${result.events.length === 1 ? '' : 's'} marked for manual review.`
        : 'The score is below the burst threshold; manual review is recommended.',
    };
  }
  return {
    status: 'clear',
    label: 'No burst detected',
    detail: 'The current FITS block did not reach the calibrated model threshold.',
  };
}
