"""Live read-only Bass smoke; --generate queues missing Bass, --preview edits a temporary catalog only."""
import argparse
import hashlib
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from app import main
import httpx
from playwright.sync_api import sync_playwright

JOB = "d0a3f98491a64544a5a86c568dc9ffef"
LEGACY = "bf7517b073b1465097bda7a19ce63d95"


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    assert not (args.generate and args.preview), "Never run inference through preview media symlinks"
    base = "http://127.0.0.1:8790" if args.preview else "http://127.0.0.1:8788"
    if args.preview:
        main.SECRET = "local-browser-test-secret-" * 3
        main.USERNAME = "browser-test"
    token = main.sign_session(main.USERNAME, "local", int(time.time()) + 1800)
    files = [main.JOBS / JOB / filename for filename in ("chordino.json", "btc.json", "stem-midi/guitar.json", "stem-midi/guitar.mid")]
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()]
    with httpx.Client(base_url=base, cookies={main.COOKIE: token}, timeout=30) as client:
        before = client.get(f"/api/jobs/{JOB}?include_notes=false").json()["result"]
        if args.generate:
            response = client.post(f"/api/jobs/{JOB}/bass-analysis", headers={"Origin": base})
            assert response.status_code == 202, response.text
        deadline = time.monotonic() + 1000
        previous = None
        while True:
            response = client.get(f"/api/jobs/{JOB}/bass-analysis")
            response.raise_for_status()
            status = response.json()["status"]
            if status != previous:
                print("bass", status, flush=True)
                previous = status
            if status == "done":
                break
            assert args.generate and status in {"queued", "working"} and time.monotonic() < deadline, response.text
            time.sleep(2)
        payload = client.get(f"/api/jobs/{JOB}/notes/bass").json()
        assert payload["notes"] and payload["profile"] == "bass_v1"
        assert all(23 <= note["midi"] <= 67 for note in payload["notes"])
        midi = client.get(f"/api/jobs/{JOB}/export/midi/bass")
        assert midi.status_code == 200 and midi.content.startswith(b"MThd")
        after = client.get(f"/api/jobs/{JOB}?include_notes=false").json()["result"]
        for field in ("methods", "key", "guitar_tab", "active_method"):
            assert before.get(field) == after.get(field), field
        assert hashes == [hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()]
        print("Bass notes", len(payload["notes"]), "original guitar/chords unchanged", flush=True)
        if not args.preview:
            legacy = client.get(f"/api/jobs/{LEGACY}/bass-analysis")
            assert legacy.status_code == 200 and legacy.json()["status"] == "done"
            legacy_file = main.JOBS / LEGACY / "stem-midi/bass.json"
            original = legacy_file.read_bytes()
            assert client.get(f"/api/jobs/{LEGACY}/notes/bass").json()["notes"]
            if args.generate:
                assert client.post(f"/api/jobs/{LEGACY}/bass-analysis", headers={"Origin": base}).json()["status"] == "done"
            assert legacy_file.read_bytes() == original
            print("Existing general Bass MIDI reused without rewriting", flush=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/opt/google/chrome/chrome", args=["--no-sandbox"])
        for name, width, height in (("desktop", 1365, 900), ("mobile", 390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height},
                is_mobile=name == "mobile", has_touch=name == "mobile")
            context.add_cookies([{"name": main.COOKIE, "value": token, "url": base}])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            page.locator("#jobsList [data-job]").first.wait_for(state="visible")
            if not page.locator(f'[data-job="{JOB}"]').count():
                page.locator("#jobsMore").click()
            page.locator(f'[data-job="{JOB}"]').click()
            page.locator('[data-result-view="tab"]').click()
            page.locator("#continuousTab .tab-system").first.wait_for(state="visible")
            page.locator(".method-options summary").click()
            page.locator("#capoSelect").select_option("2")
            page.locator("#tabInstrument").select_option("bass")
            page.wait_for_function("() => state.tabSource === 'bass' && TabStudio.inspect().count > 0")
            assert page.locator("#continuousTab .tab-system").first.locator(".tab-system-row").count() == 4
            assert "Bass 四線譜" == page.locator("#tabTitle").inner_text()
            assert page.locator("#tabEngineOption").is_hidden()
            assert page.locator("#tabEngineMidi").get_attribute("href").endswith("/export/midi/bass")
            page.locator(".tab-options summary").click()
            page.locator("#tabTuning").select_option("bass_five")
            page.wait_for_function("() => document.querySelector('#continuousTab .tab-system')?.querySelectorAll('.tab-system-row').length === 5")
            assert page.locator("#capoSelect").input_value() == "2", "Bass must not change guitar capo"
            page.locator("#tabTuning").select_option("bass_standard")
            page.wait_for_function("() => document.querySelector('#continuousTab .tab-system')?.querySelectorAll('.tab-system-row').length === 4")
            page.locator("#tabEditMode").check()
            page.locator("#continuousTab [data-note-index]").first.click()
            assert page.locator("#tabEditString option").count() == 4
            page.locator("#tabCloseDialog").click()
            page.locator("#tabEditMode").uncheck()
            # Audio remains the single master clock; view-switching does not
            # create another full-song player or transpose Bass by guitar capo.
            page.evaluate("document.querySelector('#audioPlayer').currentTime=2;TabStudio.update()")
            assert page.locator("#continuousTab .playing").count() == 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=f"/tmp/chordlab-bass-{name}.png", full_page=True)
            if args.preview:
                page.locator("#tabBpm").fill("141")
                page.locator("#tabBpm").dispatch_event("change")
                page.once("dialog", lambda dialog: dialog.dismiss())
                page.locator("#tabInstrument").select_option("guitar")
                assert page.locator("#tabInstrument").input_value() == "bass", "Do not lose unsaved edits"
                with page.expect_response(lambda r: r.request.method == "PUT" and "instrument=bass" in r.url) as saved:
                    page.locator("#tabSave").click()
                assert saved.value.status == 200
                bass_version = context.request.get(f"{base}/api/jobs/{JOB}/tab?instrument=bass").json()
                assert bass_version["document"]["instrument"] == "bass" and bass_version["document"]["capo"] == 0
                assert bass_version["document"]["rhythm"]["bpm"] == 141
                page.locator("#tabInstrument").select_option("guitar")
                page.wait_for_function("() => state.tabSource === 'guitar' && TabStudio.inspect().count > 0")
                assert page.locator("#continuousTab .tab-system").first.locator(".tab-system-row").count() == 6
                assert page.locator("#capoSelect").input_value() == "2"
                page.locator("#tabBpm").fill("142")
                page.locator("#tabBpm").dispatch_event("change")
                with page.expect_response(lambda r: r.request.method == "PUT" and "instrument=guitar" in r.url) as saved:
                    page.locator("#tabSave").click()
                assert saved.value.status == 200
                assert context.request.get(f"{base}/api/jobs/{JOB}/tab?instrument=bass").json() == bass_version
                page.locator("#tabInstrument").select_option("bass")
                page.wait_for_function("() => state.tabSource === 'bass' && document.querySelector('#tabBpm').value === '141'")
                page.reload()
                page.locator(f'[data-job="{JOB}"]').click()
                page.locator('[data-result-view="tab"]').click()
                page.locator("#tabInstrument").select_option("bass")
                page.wait_for_function("() => state.tabSource === 'bass' && document.querySelector('#tabBpm').value === '141'")
                print(name, "independent save/reload and unsaved guard passed (temporary DB)", flush=True)
            else:
                for selected in ("guitar", "bass", "guitar", "bass"):
                    page.locator("#tabInstrument").select_option(selected)
                page.wait_for_function("() => state.tabInstrument === 'bass' && state.tabSource === 'bass' && TabStudio.inspect().count > 0")
                # Missing/queued/completed UI only; mock POST prevents any
                # additional production inference or stored-document mutation.
                phase = {"submitted": False, "checks": 0, "done": False}
                def job_response(route):
                    response = route.fetch()
                    payload = response.json()
                    if not phase["done"]:
                        separation = payload["result"]["separation"]
                        separation["midi_stems"] = [stem for stem in separation["midi_stems"] if stem != "bass"]
                        payload["result"]["bass_tab"] = {"status": "pending"}
                    route.fulfill(response=response, json=payload)
                def task_response(route):
                    if route.request.method == "POST":
                        phase["submitted"] = True
                        route.fulfill(status=202, json={"status": "queued"})
                        return
                    if phase["submitted"]:
                        phase["checks"] += 1
                    if phase["checks"] >= 3:
                        phase["done"] = True
                        route.fulfill(response=route.fetch())
                    else:
                        status = "pending" if not phase["submitted"] else "queued" if phase["checks"] == 1 else "working"
                        route.fulfill(json={"status": status, "ready": False, "available": True,
                            "busy_engine": "bass" if phase["submitted"] else None})
                page.route(f"**/api/jobs/{JOB}?include_notes=false", job_response)
                page.route(f"**/api/jobs/{JOB}/bass-analysis", task_response)
                page.reload()
                page.locator("#jobsList [data-job]").first.wait_for(state="visible")
                if not page.locator(f'[data-job="{JOB}"]').count():
                    page.locator("#jobsMore").click()
                page.locator(f'[data-job="{JOB}"]').click()
                page.locator('[data-result-view="tab"]').click()
                page.locator("#tabInstrument").select_option("bass")
                page.locator("#generateGuitarTab").wait_for(state="visible")
                assert "尚未產生 Bass 譜" in page.locator("#continuousTab").inner_text()
                page.locator("#generateGuitarTab").click()
                page.wait_for_function("() => document.querySelector('#generateGuitarTab').disabled")
                page.wait_for_function("() => state.tabSource === 'bass' && TabStudio.inspect().count > 0", timeout=20000)
                assert phase["done"] and page.locator("#generateGuitarTab").is_hidden()
                print(name, "missing/submit/queue/automatic completion passed (mock responses)", flush=True)
            assert not errors, errors
            print(name, "four/five strings, capo isolation, editor, cursor and viewport passed", flush=True)
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
