import { useState } from 'react';

const ACTIVE_STATUSES = new Set(['submitting', 'queued', 'running', 'cancel_requested']);

function formatUtc(value) {
  return value ? value.slice(11, 19) : '—';
}

function formatFrequency(candidate) {
  const low = candidate.frequency_min_mhz;
  const high = candidate.frequency_max_mhz;
  return Number.isFinite(low) && Number.isFinite(high) ? `${low.toFixed(1)}–${high.toFixed(1)} MHz` : '—';
}

function isOfficialMatch(candidate) {
  return candidate.matched_official_event_id != null;
}

function isRecommended(candidate) {
  if (typeof candidate.is_recommended === 'boolean') return candidate.is_recommended;
  return candidate.source === 'ml_cnn' || isOfficialMatch(candidate);
}

function candidatePriority(candidate) {
  if (isOfficialMatch(candidate)) return 0;
  if (candidate.source === 'ml_cnn' && isRecommended(candidate)) return 1;
  if (candidate.source === 'ml_cnn') return 2;
  return 3;
}

function groupByBlock(candidates) {
  const sorted = [...candidates].sort((left, right) => (
    candidatePriority(left) - candidatePriority(right)
    || Number(right.file_score ?? 0) - Number(left.file_score ?? 0)
    || String(left.started_at).localeCompare(String(right.started_at))
  ));
  const groups = new Map();
  sorted.forEach((candidate) => {
    const key = candidate.filename ?? 'Unknown FITS block';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(candidate);
  });
  return [...groups.entries()];
}

export default function FullDayScanResult({ task, onOpenEvent }) {
  const [showResults, setShowResults] = useState(true);
  const [activeFilter, setActiveFilter] = useState('recommended');
  if (!task || task.type !== 'burst_detect_day') return null;

  const result = task.result ?? {};
  const candidates = result.candidates ?? [];
  const active = ACTIVE_STATUSES.has(task.status);
  const progress = Math.max(0, Math.min(100, Math.round((task.progress ?? 0) * 100)));
  const completed = task.status === 'succeeded';
  const mlCount = result.ml_candidates ?? candidates.filter((item) => item.source === 'ml_cnn').length;
  const heuristicCount = result.heuristic_candidates
    ?? candidates.filter((item) => item.source === 'heuristic_visual').length;
  const officialCount = result.official_matches ?? candidates.filter(isOfficialMatch).length;
  const recommendedCount = result.recommended_candidates ?? candidates.filter(isRecommended).length;
  const savedMlCount = candidates.filter(
    (candidate) => candidate.source === 'ml_cnn' && candidate.is_new,
  ).length;
  const filters = [
    { id: 'recommended', label: 'Recommended', count: recommendedCount },
    { id: 'ml', label: 'CNN+MIL', count: mlCount },
    { id: 'official', label: 'deARCE matches', count: officialCount },
    { id: 'experimental', label: 'Experimental visual', count: heuristicCount },
  ];
  const filteredCandidates = candidates.filter((candidate) => {
    if (activeFilter === 'ml') return candidate.source === 'ml_cnn';
    if (activeFilter === 'official') return isOfficialMatch(candidate);
    if (activeFilter === 'experimental') return candidate.source === 'heuristic_visual';
    return isRecommended(candidate);
  });
  const candidateGroups = groupByBlock(filteredCandidates);

  return (
    <section className={`day-scan-result ${task.status}`} aria-labelledby="day-scan-title">
      <header>
        <div>
          <p className="eyebrow">Full-day candidate scan</p>
          <h3 id="day-scan-title">{task.station} · {task.date}</h3>
        </div>
        <span className="day-scan-state">{active ? `${task.status} · ${progress}%` : task.status}</span>
      </header>

      {active && (
        <div
          className="day-scan-progress"
          role="progressbar"
          aria-label="Full-day scan progress"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow={progress}
        >
          <i style={{ width: `${progress}%` }} />
        </div>
      )}

      {task.status === 'failed' && <p className="day-scan-error">Scan failed: {task.error ?? 'Unknown worker error'}</p>}

      {completed && (
        <>
          <div className="day-scan-metrics" aria-label="Full-day scan summary">
            <span>
              <strong>{result.files_processed ?? 0}/{result.files_discovered ?? 0}</strong>
              blocks processed{result.files_skipped ? ` · ${result.files_skipped} skipped` : ''}
            </span>
            <span><strong>{mlCount}</strong>CNN+MIL candidates</span>
            <span className="experimental"><strong>{heuristicCount}</strong>experimental visual signals</span>
            <span><strong>{officialCount}</strong>deARCE matches</span>
          </div>
          <p className="day-scan-note">
            <strong>{recommendedCount} recommended for review.</strong>{' '}
            Experimental visual signals are excluded by default and are not saved automatically.
            {savedMlCount ? ` ${savedMlCount} new ML record${savedMlCount === 1 ? ' was' : 's were'} saved.` : ''}
          </p>

          {candidates.length === 0 ? (
            <p className="day-scan-empty">No ML or visual candidates were found for this station and day.</p>
          ) : (
            <>
              <div className="day-scan-toolbar">
                <div className="day-scan-filters" role="group" aria-label="Candidate source filter">
                  {filters.map((filter) => (
                    <button
                      type="button"
                      key={filter.id}
                      className={activeFilter === filter.id ? 'active' : ''}
                      aria-pressed={activeFilter === filter.id}
                      onClick={() => {
                        setActiveFilter(filter.id);
                        setShowResults(true);
                      }}
                    >
                      {filter.label} <span>{filter.count}</span>
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  className="day-scan-toggle"
                  aria-expanded={showResults}
                  aria-controls="day-scan-candidates"
                  onClick={() => setShowResults((value) => !value)}
                >
                  {showResults ? 'Hide results' : 'Show results'}
                </button>
              </div>

              {showResults && (
                <div className="day-scan-candidates" id="day-scan-candidates">
                  {activeFilter === 'experimental' && (
                    <p className="day-scan-experimental-warning" role="note">
                      Experimental heuristic output. It is sensitive to RFI and persistent station noise and must not be interpreted as a confirmed burst.
                    </p>
                  )}
                  {candidateGroups.length === 0 ? (
                    <p className="day-scan-empty">No candidates match this filter.</p>
                  ) : candidateGroups.map(([filename, blockCandidates]) => (
                    <article className="day-scan-block" key={filename}>
                      <header>
                        <strong title={filename}>{filename}</strong>
                        <span>{blockCandidates.length} {blockCandidates.length === 1 ? 'signal' : 'signals'}</span>
                      </header>
                      {blockCandidates.map((candidate, index) => (
                        <div
                          className={`day-scan-candidate${candidate.source === 'heuristic_visual' ? ' experimental' : ''}`}
                          key={`${candidate.id ?? filename}-${candidate.started_at}-${index}`}
                        >
                          <div className="day-scan-candidate-main">
                            <strong>{formatUtc(candidate.started_at)} UTC</strong>
                            <span>{candidate.source === 'ml_cnn' ? 'CNN+MIL' : 'Visual heuristic'}</span>
                            {candidate.is_burst && <span className="day-scan-confidence">High confidence</span>}
                            {candidate.source === 'heuristic_visual' && <span className="day-scan-experimental">Experimental</span>}
                            {candidate.is_new && candidate.source === 'ml_cnn' && (
                              <span className="day-scan-new">Saved in this scan</span>
                            )}
                            {isOfficialMatch(candidate) && <span className="day-scan-official">deARCE match</span>}
                          </div>
                          <div className="day-scan-candidate-meta">
                            <span>{formatFrequency(candidate)}</span>
                            <span>model score {Number(candidate.file_score ?? 0).toFixed(2)}</span>
                            {candidate.matched_official_burst_type && (
                              <span>Official type {candidate.matched_official_burst_type}</span>
                            )}
                          </div>
                          <button
                            type="button"
                            className="station-link"
                            onClick={() => onOpenEvent({
                              id: candidate.id,
                              started_at: candidate.started_at,
                              ended_at: candidate.ended_at,
                              stations: [candidate.station],
                            }, candidate.station)}
                          >
                            Open spectrogram
                          </button>
                        </div>
                      ))}
                    </article>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
