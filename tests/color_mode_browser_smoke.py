"""Read-only appearance regression; no uploads, saves or inference requests."""
import argparse
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


def assert_contrast(page, selectors):
    ratios = page.evaluate('''(selectors) => {
        function luminance(color) {
            const values = color.match(/[\\d.]+/g).slice(0,3).map(n => Number(n)/255).map(n => n <= .04045 ? n/12.92 : ((n+.055)/1.055)**2.4);
            return values[0]*.2126 + values[1]*.7152 + values[2]*.0722;
        }
        return selectors.map(selector => {
            const style = getComputedStyle(document.querySelector(selector));
            const a = luminance(style.color), b = luminance(style.backgroundColor);
            return [selector, (Math.max(a,b)+.05)/(Math.min(a,b)+.05)];
        });
    }''', selectors)
    assert all(ratio >= 4.5 for _, ratio in ratios), ratios


def select_color(page, value):
    if not page.locator('#colorMenu').evaluate('e => e.open'):
        page.locator('#colorToggle').click()
    page.select_option('#colorModeSelect', value)
    page.keyboard.press('Escape')
    page.wait_for_timeout(200)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    token = main.sign_session(main.USERNAME, 'local', int(time.time()) + 600)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/opt/google/chrome/chrome', headless=True, args=['--no-sandbox'])
        for width in (1440, 1024, 768, 390, 320):
            context = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme='light')
            context.add_cookies([{'name': main.COOKIE, 'value': token, 'url': BASE}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/**', lambda route: route.abort() if route.request.method not in {'GET', 'HEAD'} else route.continue_())
            page.goto(BASE)
            page.wait_for_function('() => state.current && state.jobs.length')
            page.evaluate('(id) => openJob(id)', JOB)
            page.wait_for_function('() => state.current?.id === "' + JOB + '" && state.chordEntries?.length')
            page.evaluate('() => {window.originalAudio = $("#audioPlayer"); window.originalJob = state.current.id;}')
            assert page.evaluate('document.documentElement.dataset.colorMode') == 'light'
            page.emulate_media(color_scheme='dark')
            page.wait_for_function('() => document.documentElement.dataset.colorMode === "dark"')
            # A color-only change must not reset an expanded advanced panel.
            page.evaluate('$("#tabAnalysisDetails").open = true')
            for color in ('light', 'dark'):
                select_color(page, color)
                assert page.locator('#tabAnalysisDetails').evaluate('e => e.open')
                assert page.evaluate('document.documentElement.dataset.colorMode') == color
                for view in ('chords', 'tab'):
                    page.locator(f'[data-result-view="{view}"]').click()
                    if view == 'tab':
                        page.wait_for_function('() => $("#continuousTab .tab-system")')
                    result = page.evaluate('''() => {
                        const root = document.documentElement, bg = getComputedStyle(root).getPropertyValue('--panel').trim();
                        const canvas = document.createElement('canvas'); const ctx = canvas.getContext('2d');
                        ctx.fillStyle = bg; const hex = ctx.fillStyle;
                        const rgb = hex.match(/\\w\\w/g).map(c => parseInt(c,16));
                        const expected = `rgb(${rgb.join(', ')})`;
                        const controls = ['#themeSelect', '#colorToggle', '.topbar .icon-button'].map(s => $(s).getBoundingClientRect());
                        return {oneAudio: originalAudio === $('#audioPlayer') && $$('#audioPlayer').length === 1,
                            sameJob: state.current.id === originalJob,
                            noOverflow: root.scrollWidth <= innerWidth + 1,
                            controlsFit: controls.every(r => r.left >= 0 && r.right <= innerWidth) && controls.every((r,i) => !i || r.left >= controls[i-1].right),
                            dockSurface: getComputedStyle($('#playerDock')).backgroundColor === expected,
                            tabSurface: getComputedStyle($('.tab-system') || $('#fullTabPanel')).backgroundColor === expected,
                            dialogSurface: getComputedStyle($('#tabNoteDialog')).backgroundColor === expected,
                            nativeColor: getComputedStyle(root).colorScheme === root.dataset.colorMode};
                    }''')
                    assert all(result.values()), (width, color, view, result)
                    assert_contrast(page, ['#importForm .primary', '#playToggle', '#themeSelect'])
                    if args.screenshots and width in (1440, 390):
                        page.evaluate('window.scrollTo(0, $("#activeWorkspace").getBoundingClientRect().top + scrollY - $(".topbar").offsetHeight - 20)')
                        page.screenshot(path=str(args.screenshots / f'{color}-{width}-{view}.png'))
                        if view == 'tab':
                            page.locator('#continuousTab').scroll_into_view_if_needed()
                            page.screenshot(path=str(args.screenshots / f'{color}-{width}-tab-notes.png'))
            # Real audio remains playing while colors change.
            page.wait_for_function('() => $("#audioPlayer").readyState >= 1')
            page.locator('#playToggle').click()
            page.wait_for_function('() => !$("#audioPlayer").paused && $("#audioPlayer").currentTime > .1')
            select_color(page, 'light')
            assert page.evaluate('!originalAudio.paused && originalAudio === $("#audioPlayer")')
            select_color(page, 'dark')
            assert page.evaluate('!originalAudio.paused')
            assert page.evaluate('getComputedStyle($(".song-sleeve .record-disc")).animationName') == 'record-turn'
            page.emulate_media(reduced_motion='reduce')
            assert page.evaluate('getComputedStyle($(".song-sleeve .record-disc")).animationName') == 'none'
            page.locator('#playToggle').click()
            assert page.evaluate('getComputedStyle($(".song-sleeve .record-disc")).animationName') == 'none'
            # Explicit dark ignores OS light; system follows live OS changes.
            page.emulate_media(color_scheme='light')
            assert page.evaluate('document.documentElement.dataset.colorMode') == 'dark'
            page.reload()
            page.wait_for_function('() => state.current')
            assert page.evaluate('document.documentElement.dataset.colorMode') == 'dark'
            page.select_option('#themeSelect', 'classic')
            assert page.evaluate('document.documentElement.dataset.colorMode') == 'light'
            assert page.locator('#colorMenu').is_hidden()
            page.select_option('#themeSelect', 'studio')
            assert page.evaluate('document.documentElement.dataset.colorMode') == 'dark'
            select_color(page, 'system')
            assert page.evaluate('document.documentElement.dataset.colorMode') == 'light'
            page.emulate_media(color_scheme='dark')
            page.wait_for_function('() => document.documentElement.dataset.colorMode === "dark"')
            page.evaluate("setPage('library')")
            page.wait_for_function('() => $(".library-card")')
            assert_contrast(page, ['.library-sort button.active'])
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            if args.screenshots and width in (1440, 390):
                page.screenshot(path=str(args.screenshots / f'dark-{width}-library.png'))
            assert not errors, errors
            print(width, 'light/dark/system/persistence/media/controls/surfaces/motion/library passed', flush=True)
            context.close()
        browser.close()


if __name__ == '__main__':
    run()
