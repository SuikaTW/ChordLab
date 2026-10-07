"""Read-only timeline following checks; mock the media clock, never save a song."""
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / '.env')
from app import main

BASE = 'http://127.0.0.1:8788'
JOB = 'd004a3af3f8246a7aaa3455235f64bbc'


def run():
    token = main.sign_session(main.USERNAME, 'local', int(time.time()) + 600)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/opt/google/chrome/chrome', headless=True, args=['--no-sandbox'])
        for width in (1365, 390, 320):
            context = browser.new_context(viewport={'width': width, 'height': 900}, is_mobile=width < 500, has_touch=width < 500)
            context.add_cookies([{'name': main.COOKIE, 'value': token, 'url': BASE}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/**', lambda route: route.abort() if route.request.method not in {'GET', 'HEAD'} else route.continue_())
            page.goto(BASE)
            page.wait_for_function('() => state.current && state.jobs.length')
            page.evaluate('(id) => openJob(id)', JOB)
            page.wait_for_function('() => state.chordEntries?.length > 1')
            page.evaluate('''() => {
                const player = $('#audioPlayer'); player.pause();
                window.testClock = {time: 0, paused: false};
                Object.defineProperty(player, 'currentTime', {get: () => testClock.time, configurable: true});
                Object.defineProperty(player, 'paused', {get: () => testClock.paused, configurable: true});
                state.chordTouched = -Infinity; $('#followChords').checked = true;
                window.savedSelection = state.selected;
                window.savedY = scrollY;
                const entry = state.chordEntries[Math.floor(state.chordEntries.length * .7)];
                testClock.time = entry.start + (entry.end - entry.start) * .5;
                markPlaying();
            }''')
            result = page.evaluate('''() => {
                const timeline = $('#timeline'), head = state.chordPlayhead.getBoundingClientRect(), rect = timeline.getBoundingClientRect();
                return {scroll: timeline.scrollLeft, visible: head.left >= rect.left && head.left <= rect.right,
                    highlighted: $$('.chord-block.playing').length, selected: state.selected === savedSelection, y: scrollY === savedY};
            }''')
            assert result['scroll'] > 0 and result['visible'] and result['highlighted'] == 1 and result['selected'] and result['y'], result
            page.evaluate('''() => {
                $('#timeline').dispatchEvent(new Event('touchstart'));
                $('#timeline').scrollLeft = 0; markPlaying();
            }''')
            assert page.evaluate("$('#timeline').scrollLeft") == 0, 'Manual browsing must temporarily suppress follow'
            page.evaluate('state.chordTouched = performance.now() - 5100; markPlaying()')
            assert page.evaluate("$('#timeline').scrollLeft") > 0
            page.evaluate("$('#followChords').checked = false; $('#followChords').dispatchEvent(new Event('change')); $('#timeline').scrollLeft = 0; markPlaying()")
            assert page.evaluate("$('#timeline').scrollLeft") == 0
            assert page.evaluate("localStorage.getItem('followChords')") == 'off'
            page.evaluate("$('#followChords').checked = true; testClock.paused = true; markPlaying()")
            assert page.evaluate("$('#timeline').scrollLeft") == 0, 'Paused playback must not scroll'
            page.evaluate("testClock.time = state.current.duration + 1; markPlaying()")
            assert page.evaluate("state.chordPlayhead.classList.contains('hidden') && !$('.chord-block.playing')")
            page.evaluate('''() => {
                testClock.paused = false; testClock.time = state.chordEntries[1].start;
                state.chordTouched = -Infinity; animatePlayback();
            }''')
            page.wait_for_function('() => state.chordActive === 1')
            page.evaluate('testClock.paused = true')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert not errors, errors
            print(width, 'highlight/playhead/follow/manual grace/off/pause/gaps/animation/no vertical jumps passed', flush=True)
            context.close()
        browser.close()


if __name__ == '__main__':
    run()
