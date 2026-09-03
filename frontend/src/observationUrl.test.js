import { describe, expect, it } from 'vitest';

import { observationPath, parseObservationSearch } from './observationUrl';

describe('observation links', () => {
  it('parses canonical and legacy parameter names', () => {
    const canonical = parseObservationSearch(
      '?station=GLASGOW&date=2026-08-25&filename=GLASGOW_20260825_123001_01.fit.gz',
    );
    const legacy = parseObservationSearch(
      '?estacion=GLASGOW&fecha=2026-08-25&archivo=GLASGOW_20260825_123001_01.fit.gz',
    );

    expect(canonical.error).toBeNull();
    expect(legacy.observation).toEqual(canonical.observation);
    expect(canonical.observation).toMatchObject({
      station: 'GLASGOW',
      date: '2026-08-25',
      filename: 'GLASGOW_20260825_123001_01.fit.gz',
      focusCode: '01',
      startedAt: '2026-08-25T12:30:01Z',
    });
  });

  it('rejects incomplete, traversing and mismatched observations', () => {
    expect(parseObservationSearch('?station=MRO').error).toMatch(/station, date and filename/);
    expect(parseObservationSearch(
      '?station=MRO&date=2026-08-25&filename=../secret.fit',
    ).error).toMatch(/invalid FITS filename/);
    expect(parseObservationSearch(
      '?station=MRO&date=2026-08-25&filename=BIR_20260825_120000_01.fit.gz',
    ).error).toMatch(/does not belong/);
  });

  it('writes only canonical parameters into shared paths', () => {
    expect(observationPath({
      station: 'MRO',
      date: '2026-08-25',
      filename: 'MRO_20260825_120000_01.fit.gz',
    }, { pathname: '/studio/', hash: '' })).toBe(
      '/studio/?station=MRO&date=2026-08-25&filename=MRO_20260825_120000_01.fit.gz',
    );
  });
});
