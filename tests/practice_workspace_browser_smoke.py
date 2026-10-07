"""Read-only score-first workflow regression; all write APIs are blocked."""
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
    token = main.sign_session(main.USERNAME, 'local', int(time.time()) + 900)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/opt/google/chrome/chrome', headless=True, args=['--no-sandbox'])
        for width in (1440, 1024, 768, 390, 320):
            context = browser.new_context(viewport={'width':width,'height':900}, is_mobile=width<500, has_touch=width<500)
            context.add_cookies([{'name':main.COOKIE,'value':token,'url':BASE}])
            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/**', lambda route: route.abort() if route.request.method not in {'GET','HEAD'} else route.continue_())
            page.goto(BASE)
            page.wait_for_function('() => state.current && state.jobs.length')
            page.evaluate('(id) => openJob(id)', JOB)
            page.wait_for_function('() => state.current?.id === "'+JOB+'" && state.chordEntries?.length')
            assert page.locator('.account-menu > summary').is_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), 'Header or workspace overflows viewport'
            page.evaluate('window.savedAudio = $("#audioPlayer")')
            assert page.locator('.import-panel').is_hidden()
            if width <= 720:
                assert page.locator('.left-rail').is_hidden()
                assert page.locator('#workTitle').bounding_box()['y'] < 200
            page.locator('#songPickerToggle').click()
            assert page.locator('.import-panel').is_visible()
            assert page.locator('#jobsList').is_visible()
            page.keyboard.press('Escape')
            assert page.locator('.import-panel').is_hidden()
            assert page.evaluate('savedAudio === $("#audioPlayer") && state.current.id === "'+JOB+'"')
            page.evaluate("setPage('library')")
            page.locator('[data-new-song]').click()
            assert page.locator('.import-panel').is_visible()
            page.keyboard.press('Escape')
            # Tools remain reachable, without duplicating the controls.
            page.locator('#workspaceUtilities > summary').click()
            assert page.locator('#trackRow').is_visible()
            assert page.evaluate('$$ ("#trackSwitch").length === 1')
            page.locator('.method-options > summary').click()
            assert page.locator('.method-switch').is_visible()
            page.keyboard.press('Escape')
            page.locator('[data-result-view="tab"]').click()
            page.wait_for_function('() => $("#continuousTab [data-note-index]") && $("#continuousTab").getAttribute("aria-busy") !== "true"')
            assert_tab_alignment(page)
            score = page.evaluate('TabStudio.inspect()')
            assert score['layoutHeight'] == 202
            if width == 1440:
                assert score['maxBarsPerRow'] > 2, score
            assert page.evaluate('document.body.classList.contains("compact-player")')
            compact_height = page.locator('#playerDock').bounding_box()['height']
            assert compact_height < 80, compact_height
            assert page.locator('#volumeSlider').is_hidden()
            page.wait_for_function('() => $("#audioPlayer").readyState >= 1')
            page.locator('#playToggle').click()
            page.wait_for_function('() => !$("#audioPlayer").paused && $("#audioPlayer").currentTime > .1')
            page.locator('#dockSizeToggle').click()
            assert page.locator('#volumeSlider').is_visible()
            assert page.locator('#playerDock').bounding_box()['height'] > compact_height
            assert page.evaluate('!savedAudio.paused && savedAudio === $("#audioPlayer")')
            page.locator('#volumeSlider').evaluate("e => {e.value='.4';e.dispatchEvent(new Event('input',{bubbles:true}));}")
            assert page.evaluate('state.volume') == .4
            page.locator('#dockSizeToggle').click()
            assert page.evaluate('!savedAudio.paused && state.volume === .4')
            page.locator('#playToggle').click()
            page.wait_for_function('() => $("#audioPlayer").paused')
            # Unsaved edits survive presentation-only resize and style changes.
            page.locator('#tabEditMode').check()
            page.locator('#continuousTab [data-note-index]').first.click()
            fret = int(page.locator('#tabEditFret').input_value())
            page.locator('#tabEditFret').fill(str(min(24, fret+1)))
            page.locator('#tabNoteForm button[type="submit"]').click()
            edited = page.evaluate('TabStudio.inspect()')
            assert edited['dirty']
            for target_width in (390, 1440, width):
                page.set_viewport_size({'width':target_width,'height':900})
                page.wait_for_timeout(250)
                assert_tab_alignment(page)
                current = page.evaluate('TabStudio.inspect()')
                assert current['count'] == edited['count'] and current['dirty'], current
            page.select_option('#themeSelect', 'classic')
            page.wait_for_timeout(250)
            assert page.evaluate('TabStudio.inspect().layoutHeight') == 230
            assert page.evaluate('TabStudio.inspect().dirty')
            assert page.evaluate('$("#trackToolsSlot").nextElementSibling.id === "trackRow"')
            assert page.locator('.import-panel').is_visible()
            page.select_option('#themeSelect', 'studio')
            page.wait_for_timeout(250)
            assert_tab_alignment(page)
            assert page.locator('#tabSave').is_enabled()
            # Windowed score remains bounded and reaches the last systems.
            page.locator('#tabFlowViewport').evaluate('e => e.scrollTop = e.scrollHeight')
            page.wait_for_timeout(250)
            assert page.locator('[data-tab-system]').count() < 20
            final = page.evaluate('TabStudio.inspect()')
            last_index = int(page.locator('[data-tab-system]').last.get_attribute('data-tab-system'))
            assert last_index == final['rowCount']-1, (last_index,final)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            if args.screenshots and width in (1440,390):
                page.locator('#tabFlowViewport').evaluate('e => e.scrollTop = 0')
                page.evaluate('window.scrollTo(0, $("#fullTabPanel").getBoundingClientRect().top+scrollY-$(".topbar").offsetHeight-12)')
                page.wait_for_timeout(250)
                page.screenshot(path=str(args.screenshots/f'practice-{width}-score.png'))
            assert not errors, errors
            print(width,'picker/tools/compact playback/volume/resize/unsaved edits/classic/virtualization passed',flush=True)
            context.close()
        browser.close()


if __name__ == '__main__':
    run()
