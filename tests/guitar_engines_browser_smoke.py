"""Live desktop/mobile engine switching; generation is explicit with --generate.

Requires the existing local-admin environment and an already analyzed pure guitar
job. Does not change baseline notes, chords or personal TAB. Snapshots use /tmp.
"""
from pathlib import Path
import argparse
import hashlib
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from app import main
import httpx
from playwright.sync_api import sync_playwright


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", default="cb4455ee4bce40b3974383fb393d835d")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    base = "http://127.0.0.1:8788"
    token = main.sign_session(main.USERNAME, "local", int(time.time()) + 1800)
    paths = [main.JOBS / args.job / "stem-midi" / name for name in ("guitar.json", "guitar.mid")]
    baseline = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    with httpx.Client(base_url=base, cookies={main.COOKIE: token}, timeout=30) as client:
        before = client.get(f"/api/jobs/{args.job}?include_notes=false").json()
        assert before["pure_guitar"]
        for engine in ("gaps", "tabcnn", "hybrid"):
            if args.generate:
                response = client.post(f"/api/jobs/{args.job}/guitar-analysis?engine={engine}", headers={"Origin": base})
                assert response.status_code == 202, response.text
            deadline = time.monotonic() + 900
            previous = None
            while True:
                response = client.get(f"/api/jobs/{args.job}/guitar-analysis?engine={engine}")
                response.raise_for_status()
                status = response.json()["status"]
                if status != previous:
                    print(engine, status, flush=True)
                    previous = status
                if status == "done":
                    break
                assert args.generate and status in {"queued", "working"} and time.monotonic() < deadline, response.text
                time.sleep(2)
            response = client.get(f"/api/jobs/{args.job}/notes/guitar?engine={engine}")
            response.raise_for_status()
            payload = response.json()
            assert payload["notes"] and payload["experimental"]
            midi = client.get(f"/api/jobs/{args.job}/guitar-midi/{engine}")
            assert midi.status_code == 200 and midi.content.startswith(b"MThd")
            print(engine, "notes", len(payload["notes"]), "worker seconds", payload["elapsed_seconds"], flush=True)
        after = client.get(f"/api/jobs/{args.job}?include_notes=false").json()
        assert before["result"]["methods"] == after["result"]["methods"]
        assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths] == baseline
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
            page.locator(f'[data-job="{args.job}"]').click()
            page.locator('[data-result-view="tab"]').click()
            page.locator("#continuousTab .tab-system").first.wait_for(state="visible")
            for engine in ("gaps", "tabcnn", "hybrid", "basic_pitch", "gaps"):
                page.locator("#tabEngine").select_option(engine)
                page.wait_for_function("engine => state.tabEngine === engine && state.tabSource === 'guitar' && state.tabProfile.includes(engine === 'basic_pitch' ? 'guitar_v2' : engine)", arg=engine)
                page.locator("#continuousTab .tab-system").first.wait_for(state="visible")
                assert not page.locator("#generateGuitarTab").is_visible()
                assert page.locator("#tabEngineMidi").is_visible()
                assert page.locator("#tabEngineMidi").get_attribute("href").endswith(engine)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            # Rapid changes must not allow a stale response to replace the final selection.
            page.evaluate("for (const engine of ['tabcnn','basic_pitch','gaps']) { const select=document.querySelector('#tabEngine');select.value=engine;select.dispatchEvent(new Event('change')); }")
            page.wait_for_function("() => state.tabEngine === 'gaps' && state.tabSource === 'guitar' && state.tabProfile === 'guitar_gaps_v1'")
            page.locator("#continuousTab .tab-system").first.wait_for(state="visible")
            assert not errors, errors
            page.screenshot(path=f"/tmp/chordlab-guitar-engines-{name}.png", full_page=True)
            print(name, "switching, rapid switching, layout and MIDI controls passed", flush=True)
            busy = {"calls": 0}
            def shared_task(route):
                response = route.fetch()
                payload = response.json()
                busy["calls"] += 1
                payload["busy_engine"] = "chord_v2" if busy["calls"] == 1 else None
                route.fulfill(response=response, json=payload)
            page.route(f"**/api/jobs/{args.job}/guitar-analysis?engine=hybrid", shared_task)
            page.locator("#tabEngine").select_option("hybrid")
            page.wait_for_function("() => state.tabEngine === 'hybrid' && state.tabProfile === 'guitar_hybrid_v2' && TabStudio.inspect().count > 0")
            page.locator(".tab-options summary").click()
            page.locator("#tabBpm").fill("141")
            page.locator("#tabBpm").dispatch_event("change")
            assert page.evaluate("TabStudio.inspect().dirty")
            page.wait_for_timeout(3200)
            assert busy["calls"] >= 2
            assert page.evaluate("TabStudio.inspect().dirty"), "Background completion discarded unsaved TAB changes"
            assert page.locator("#tabBpm").input_value() == "141"
            assert not errors, errors
            print(name, "unsaved TAB survives shared-analysis completion (mock status)", flush=True)
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
