import { describe, expect, it } from 'vitest';
import { displayBlockTime, selectCombineBlocks } from './fileBlocks';

const file = (time, focus = '62', station = 'MEXICO-LANCE', ext = 'fit.gz') => ({
  filename: `${station}_20260903_${time.replaceAll(':', '')}${focus ? `_${focus}` : ''}.${ext}`,
  time, focus_code: focus, label: time,
});

describe('nominal block labels', () => {
  it.each([
    ['16:44:59', '16:45:00', true, 0],
    ['17:14:58', '17:15:00', true, 0],
    ['16:15:01', '16:15:00', true, 0],
    ['16:14:57', '16:14:57', false, 0],
    ['16:42:59', '16:42:59', false, 0],
    ['16:45:00', '16:45:00', false, 0],
    ['16:59:59', '17:00:00', true, 0],
    ['23:59:59', '00:00:00', true, 1],
  ])('%s displays as %s without mutating source time', (time, display, approximate, dayOffset) => {
    expect(displayBlockTime(time)).toEqual({ time: display, approximate, dayOffset });
  });
});

describe('combine selection', () => {
  it('selects an hour from one Mexico receiver, not two times from two receivers', () => {
    const files = ['16:14:59', '16:29:59', '16:44:59', '16:59:59'].flatMap((time) => [file(time), file(time, '63')]);
    expect(selectCombineBlocks(files, files[0].filename)).toEqual({
      filenames: files.filter((f) => f.focus_code === '62').map((f) => f.filename),
      focusCode: '62', notice: '',
    });
  });

  it('keeps Siguenza FC 02 even when FC 01 files interleave', () => {
    const files = ['16:15', '16:30', '16:45', '17:00'].flatMap((t) => [
      file(`${t}:00`, '01', 'SPAIN-SIGUENZA'), file(`${t}:01`, '02', 'SPAIN-SIGUENZA'),
    ]);
    expect(selectCombineBlocks(files, files[1].filename).filenames).toEqual(
      files.filter((f) => f.focus_code === '02').map((f) => f.filename),
    );
  });

  it('preserves the selected compressed copy without double-counting other extensions', () => {
    const files = ['16:00:00', '16:15:00', '16:30:00', '16:45:00'].flatMap((t) => [file(t, null), file(t, null, 'MEXICO-LANCE', 'fits')]);
    const result = selectCombineBlocks(files.toReversed(), files[0].filename);
    expect(result.filenames).toHaveLength(4);
    expect(result.filenames[0]).toBe(files[0].filename);
    expect(result.focusCode).toBeNull();
  });

  it('stops at missing or overlapping blocks and never hides a partial interval', () => {
    const files = ['16:00:00', '16:15:00', '16:45:00', '17:00:00'].map((t) => file(t));
    const result = selectCombineBlocks(files, files[0].filename);
    expect(result.filenames).toHaveLength(2);
    expect(result.notice).toMatch(/gap/);
    const end = selectCombineBlocks(files, files.at(-1).filename);
    expect(end.filenames).toHaveLength(1);
    expect(end.notice).toMatch(/Only 1 consecutive block/);
  });
});
