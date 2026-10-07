"""Geometry assertions shared by read-only browser regressions."""


def assert_tab_alignment(page):
    result = page.evaluate('''() => {
        const rows = [...document.querySelectorAll('#continuousTab .tab-system-row')];
        let notes = 0, maxLabelError = 0, maxNoteError = 0, maxSustainError = 0;
        const failures = [];
        const center = rect => rect.top + rect.height / 2;
        for (const row of rows) {
            const string = row.querySelector('.tab-system-string');
            const rect = string.getBoundingClientRect();
            const line = getComputedStyle(string, '::before');
            const axis = rect.top + parseFloat(line.top);
            if (line.content === 'none' || line.height !== '1px') failures.push('missing string line');
            const label = row.querySelector('b').getBoundingClientRect();
            maxLabelError = Math.max(maxLabelError, Math.abs(center(label) - axis));
            for (const note of string.querySelectorAll('button')) {
                notes++;
                const box = note.getBoundingClientRect();
                maxNoteError = Math.max(maxNoteError, Math.abs(center(box) - axis));
                if (box.top < rect.top - 1 || box.bottom > rect.bottom + 1) failures.push('note outside row');
            }
            for (const sustain of string.querySelectorAll('.tab-sustain')) {
                maxSustainError = Math.max(maxSustainError, Math.abs(center(sustain.getBoundingClientRect()) - axis));
            }
        }
        return {rows: rows.length, notes, maxLabelError, maxNoteError, maxSustainError, failures};
    }''')
    assert result['rows'] > 0 and result['notes'] > 0, result
    assert not result['failures'], result
    assert max(result['maxLabelError'], result['maxNoteError'], result['maxSustainError']) < 1, result
    return result
