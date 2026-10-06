"""Run using uv run --no-project --with playwright python tests/browser_guitar.py."""
import json
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8790"


def run():
    server = subprocess.Popen([str(ROOT / ".venv/bin/python"), str(ROOT / "tests/guitar_preview_server.py")], cwd=ROOT)
    try:
        for _ in range(60):
            if server.poll() is not None:
                raise RuntimeError("Preview server exited")
            try:
                urllib.request.urlopen(BASE + "/healthz", timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("Preview server not ready")
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
            for name, size in (("desktop", {"width": 1365, "height": 900}), ("mobile", {"width": 390, "height": 844})):
                context = browser.new_context(viewport=size, reduced_motion="reduce")
                login = context.request.post(BASE + "/login", form={"username": "browser-test", "password": "local-browser-test-password"})
                assert login.ok, login.status
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
                page.goto(BASE)
                page.wait_for_function("() => state.current?.status === 'done'")
                assert page.evaluate('state.tabJob === null'), 'Do not load TAB until requested'
                assert page.locator('[data-track="piano"]').count() == 0, 'Weak track hidden by default'
                assert page.locator('#stemDownloads a[href$="/audio/piano"]').count() == 0
                source_before = page.locator('#audioPlayer').get_attribute('src')
                page.locator('#showWeakTracks').check()
                assert page.locator('[data-track="piano"]').count() == 1
                assert page.locator('#stemDownloads a[href$="/audio/piano"]').count() == 1
                assert page.locator('#audioPlayer').get_attribute('src') == source_before, 'Reveal alone must not reload player'
                job_id = page.evaluate('state.current.id')
                assert context.request.get(BASE + f'/api/jobs/{job_id}/audio/piano', headers={'Range': 'bytes=0-15'}).ok
                page.locator('#showWeakTracks').uncheck()
                assert page.locator('[data-track="piano"]').count() == 0
                page.locator('[data-result-view="tab"]').click()
                page.wait_for_function("() => state.tabNotes.length > 0")
                base_revision = page.evaluate('TabStudio.inspect().revision')
                page.wait_for_function("() => document.querySelectorAll('[data-tab-start]').length > 0")
                page.locator('#guitarPreview').click()
                page.wait_for_function('() => document.querySelector("#guitarPreviewPlayer").readyState >= 1')
                assert 19 <= page.evaluate('document.querySelector("#guitarPreviewPlayer").duration') <= 21
                assert page.evaluate('document.querySelector("#audioPlayer").paused')
                page.locator('#guitarPreviewPlayer').evaluate('(node) => node.pause()')
                assert page.evaluate('TabStudio.inspect().count') > 501, "New TAB should retain weak/short events"
                assert page.locator('[data-tab-system]').count() <= 10, 'Only visible TAB rows should be mounted'
                page.locator('.tab-options > summary').click()
                page.locator('#tabTuning').select_option('drop_d')
                page.locator('#capoSelect').select_option('2')
                page.wait_for_function("() => state.tabWorker === null && state.capo === 2 && state.tabTuning === 'drop_d'")
                page.locator('[data-tab-density="full"]').click()
                page.wait_for_function("() => state.tabWorker === null && state.tabDensity === 'full'")
                # Rapid changes must cancel stale worker output and finish on the last selection.
                page.evaluate("() => {for(const tuning of ['standard','dadgad','drop_d']){const s=document.querySelector('#tabTuning');s.value=tuning;s.dispatchEvent(new Event('change'))}}")
                page.wait_for_function("() => state.tabWorker === null && state.tabTuning === 'drop_d'")
                assert page.locator('.tab-system').first.locator('.tab-system-row').count() == 6
                assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth"), "Page must not overflow on mobile"
                assert 'error' not in (page.locator('#toast').get_attribute('class') or ''), page.locator('#toast').inner_text()
                page.locator('#tabVoice').select_option('high')
                page.locator('#tabPosition').select_option('middle')
                page.wait_for_function("() => state.tabWorker === null && TabStudio.inspect().count > 0")
                page.locator('.tab-options > summary').click()
                page.locator('#tabEditMode').check()
                note_button = page.locator('[data-note-index]').first
                note_index = note_button.get_attribute('data-note-index')
                note_button.click()
                old_fret = int(page.locator('#tabEditFret').input_value())
                max_fret = int(page.locator('#tabEditFret').get_attribute('max'))
                new_fret = old_fret + 1 if old_fret < max_fret else old_fret - 1
                page.locator('#tabEditFret').fill(str(new_fret))
                page.locator('#tabNoteForm button[type="submit"]').click()
                assert page.locator(f'[data-note-index="{note_index}"]').inner_text() == str(new_fret)
                assert page.locator('#tabSave').is_enabled()
                with page.expect_response(lambda response: response.url.endswith('/tab') and response.request.method == 'PUT') as saved:
                    page.locator('#tabSave').click()
                assert saved.value.ok, [(error.get('loc'), error.get('msg')) for error in saved.value.json().get('detail', [])]
                assert saved.value.json()['revision'] == base_revision + 1, (base_revision, saved.value.json()['revision'])
                page.wait_for_function(f'() => TabStudio.inspect().revision === {base_revision + 1} && !TabStudio.inspect().dirty')
                page.locator(f'[data-note-index="{note_index}"]').click()
                count_before = page.evaluate('TabStudio.inspect().count')
                page.locator('#tabDeleteNote').click()
                assert page.evaluate('TabStudio.inspect().count') == count_before - 1
                page.locator('#tabUndo').click()
                assert page.evaluate('TabStudio.inspect().count') == count_before
                page.locator('#tabSave').click()
                page.wait_for_function(f'() => TabStudio.inspect().revision === {base_revision + 2} && !TabStudio.inspect().dirty')
                page.locator('#tabFlowViewport').evaluate('(node) => node.scrollTop = node.scrollHeight - node.clientHeight')
                page.wait_for_function('() => Number(document.querySelector("[data-tab-system]").dataset.tabSystem) > 0')
                assert page.locator('[data-tab-system]').count() <= 10
                page.screenshot(path=f'/tmp/chordlab-studio-{name}.png', full_page=False)
                page.screenshot(path=f"/tmp/chordlab-tab-{name}.png", full_page=False)
                page.locator('.analysis-options > summary').click()
                page.locator('label:has(#pureGuitar)').click()
                assert page.locator('#separateStems').is_disabled()
                assert page.locator('#guitarTabOnly').is_disabled()
                page.locator('label:has(#pureGuitar)').click()
                page.locator('#analysisPreset').select_option('guitar')
                assert page.locator('#separateStems').is_checked()
                assert page.locator('[name="separation_model"]').input_value() == 'htdemucs_6s'
                page.locator('.analysis-options > summary').click()
                page.reload()
                page.wait_for_function("() => state.current?.status === 'done'")
                page.locator('[data-result-view="tab"]').click()
                page.wait_for_function(f'() => state.tabNotes.length > 0 && TabStudio.inspect().revision === {base_revision + 2}')
                assert page.locator('#tabTuning').input_value() == 'drop_d', "Tuning must persist per song"
                assert page.locator('#capoSelect').input_value() == '2', "Capo must persist per song"
                assert page.locator('#tabVoice').input_value() == 'high'
                assert page.locator('#tabPosition').input_value() == 'middle'
                assert page.locator(f'[data-note-index="{note_index}"]').inner_text() == str(new_fret)
                # Review first, then explicitly queue a guitar transcription.
                review_id = ('a' if name == 'desktop' else 'b') * 32
                page.evaluate('(id) => openJob(id)', review_id)
                page.wait_for_function('(id) => state.current?.id === id', arg=review_id)
                page.locator('[data-result-view="tab"]').click()
                page.wait_for_function('() => document.querySelector("#generateGuitarTab").textContent === "產生 TAB" && !document.querySelector("#generateGuitarTab").classList.contains("hidden")')
                assert page.evaluate('state.tabSource') == 'unavailable'
                page.locator('#guitarPreview').click()
                page.wait_for_function('() => document.querySelector("#guitarPreviewPlayer").readyState >= 1')
                page.locator('#guitarPreviewPlayer').evaluate('(node) => node.pause()')
                page.locator('#generateGuitarTab').click()
                page.wait_for_function('() => state.tabSource === "guitar" && TabStudio.inspect().count > 0')
                assert page.locator('#generateGuitarTab').is_hidden()
                assert page.locator('#stemDownloads a[href$="/export/midi/guitar"]').count() == 1
                assert not errors, errors
                print(json.dumps({"viewport": name, "errors": errors, "status": "passed"}), flush=True)
                context.close()
            browser.close()
    finally:
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.terminate()
            server.wait(timeout=5)


if __name__ == "__main__":
    run()
