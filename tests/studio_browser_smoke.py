"""Read-only responsive style/dock regression. Audio clock is mocked locally."""
import argparse
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from tab_geometry import assert_tab_alignment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / '.env')
from app import main

BASE = 'http://127.0.0.1:8788'
JOB = 'd004a3af3f8246a7aaa3455235f64bbc'


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
            context = browser.new_context(viewport={'width': width, 'height': 900}, is_mobile=width < 500, has_touch=width < 500)
            context.add_cookies([{'name': main.COOKIE, 'value': token, 'url': BASE}])
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/**', lambda route: route.abort() if route.request.method not in {'GET', 'HEAD'} else route.continue_())
            page.goto(BASE)
            page.wait_for_function('() => state.current && state.jobs.length')
            page.evaluate('(id) => openJob(id)', JOB)
            page.wait_for_function('() => state.current?.id === "' + JOB + '" && state.chordEntries?.length')
            fonts = page.evaluate('''async () => {
                const latin = await document.fonts.load('500 16px "ChordLab Manrope"', 'ChordLab');
                const chinese = await document.fonts.load('500 16px "ChordLab Noto TC"', '歌曲分析與吉他');
                return latin.length > 0 && chinese.length > 0 && [...latin, ...chinese].every(font => font.status === 'loaded');
            }''')
            assert fonts, 'Both self-hosted font families must really load'
            # Exercise the actual media control before replacing the clock.
            page.wait_for_function('() => $("#audioPlayer").readyState >= 1')
            page.locator('#playToggle').click()
            page.wait_for_function('() => !$("#audioPlayer").paused && $("#audioPlayer").currentTime > .1')
            before_theme_time = page.evaluate("$('#audioPlayer').currentTime")
            page.select_option('#themeSelect', 'classic')
            page.wait_for_function('(t) => !$("#audioPlayer").paused && $("#audioPlayer").currentTime > t', arg=before_theme_time)
            page.select_option('#themeSelect', 'studio')
            page.locator('#playToggle').click()
            page.wait_for_function('() => $("#audioPlayer").paused')
            page.locator('#volumeSlider').evaluate("el => {el.value = '.45'; el.dispatchEvent(new Event('input', {bubbles: true}));}")
            assert page.evaluate('state.volume') == .45
            assert page.locator('#volumeValue').inner_text() == '45%'
            page.evaluate('''() => {
                window.savedAudio = $('#audioPlayer'); window.savedSource = savedAudio.currentSrc;
                window.savedJob = state.current.id;
                const player = savedAudio; player.pause();
                window.testClock = {time: 35, paused: true};
                Object.defineProperty(player, 'currentTime', {get: () => testClock.time, configurable: true});
                Object.defineProperty(player, 'paused', {get: () => testClock.paused, configurable: true});
                paintPlayback();
            }''')
            for theme in ('studio', 'classic'):
                page.select_option('#themeSelect', theme)
                assert page.evaluate('document.documentElement.dataset.theme') == theme
                if theme == 'studio':
                    page.locator('#workspaceUtilities > summary').click()
                    assert page.locator('#practiceTools > summary').is_visible()
                    page.locator('#practiceTools > summary').click()
                    assert page.locator('#playbackSpeed').is_visible()
                    page.locator('#practiceTools > summary').click()
                    page.keyboard.press('Escape')
                    assert not page.locator('#workspaceUtilities').evaluate('e => e.open')
                else:
                    assert page.evaluate('$("#practiceSlot").nextElementSibling.id === "practiceTools"')
                    assert page.evaluate('$("#downloadsSlot").nextElementSibling.id === "stemDownloadsPanel"')
                for view in ('chords', 'tab'):
                    page.locator(f'[data-result-view="{view}"]').click()
                    if view == 'chords' and theme == 'studio':
                        assert page.evaluate('$$ (".chord-block").every(button => button.scrollWidth <= button.clientWidth + 1)'), 'Larger chord names must not be clipped'
                    if view == 'tab':
                        page.wait_for_function('() => $("#continuousTab .tab-system") && !$("#fullTabPanel").classList.contains("result-hidden")')
                        assert_tab_alignment(page)
                        if theme == 'studio':
                            assert not page.locator('#tabAnalysisDetails').evaluate('e => e.open')
                            assert page.locator('#tabSave').is_hidden()
                            assert page.locator('#tabWarnings').is_visible() or page.locator('#tabWarnings').evaluate('e => e.classList.contains("hidden")')
                            page.locator('#tabAnalysisDetails > summary').click()
                            assert page.locator('#tabEngineOption > summary').is_visible()
                            page.locator('#tabAnalysisDetails > summary').click()
                        else:
                            assert page.locator('#tabAnalysisDetails').evaluate('e => e.open')
                    if args.screenshots and width in (1440, 390):
                        page.screenshot(path=str(args.screenshots / f'{theme}-{width}-{view}-overview.png'))
                    page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
                    page.wait_for_timeout(300)
                    result = page.evaluate('''() => {
                        const dock = $('#playerDock').getBoundingClientRect(), play = $('#playToggle').getBoundingClientRect();
                        const top = document.elementFromPoint(play.x + play.width / 2, play.y + play.height / 2);
                        const header = $('.topbar').getBoundingClientRect(), theme = $('#themeSelect').getBoundingClientRect();
                        return {visible: dock.top >= 0 && dock.bottom <= innerHeight && dock.left >= 0 && dock.right <= innerWidth,
                            clickable: !!top?.closest('#playToggle'), fixed: getComputedStyle($('#playerDock')).position === 'fixed',
                            noOverflow: document.documentElement.scrollWidth <= innerWidth + 1,
                            oneAudio: $$('#audioPlayer').length === 1 && savedAudio === $('#audioPlayer'),
                            retained: savedAudio.currentTime === 35 && savedSource === savedAudio.currentSrc && state.current.id === savedJob,
                            themeInHeader: theme.left >= header.left && theme.right <= header.right};
                    }''')
                    assert all(result.values()), (width, theme, view, result)
                    if args.screenshots and width in (1440, 390):
                        page.screenshot(path=str(args.screenshots / f'{theme}-{width}-{view}.png'))
                page.evaluate("setPage('library')")
                assert page.locator('#playerDock').is_hidden()
                page.evaluate("setPage('workspace')")
                assert page.locator('#playerDock').is_visible()
            # Style preference survives a fresh page. The mock clock is not persisted.
            page.reload()
            page.wait_for_function('() => state.current')
            assert page.evaluate('document.documentElement.dataset.theme') == 'classic'
            page.select_option('#themeSelect', 'studio')
            page.evaluate("setPage('library')")
            page.wait_for_function('() => state.libraryItems !== undefined || $("#librarySummary").textContent !== "讀取公開分析…"')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            if args.screenshots and width in (1440, 390):
                page.screenshot(path=str(args.screenshots / f'studio-{width}-library.png'))
            assert not errors, errors
            print(width, 'both styles/dock clickable/no overlap/no reload/one audio/preferences/library passed', flush=True)
            context.close()
        browser.close()


if __name__ == '__main__':
    run()
