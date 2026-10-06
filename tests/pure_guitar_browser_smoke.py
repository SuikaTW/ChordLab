"""Read-only live UI smoke test; failure responses are simulated in the browser."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from app import main
import time
from playwright.sync_api import sync_playwright

JOB = "cb4455ee4bce40b3974383fb393d835d"


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/google/chrome/chrome", args=["--no-sandbox"])
        for name, width, height in (("desktop", 1365, 900), ("mobile", 390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height},
                                         is_mobile=name == "mobile", has_touch=name == "mobile")
            context.add_cookies([{"name": main.COOKIE, "value": main.sign_session(main.USERNAME, "local", int(time.time())+600), "url": "http://127.0.0.1:8788"}])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            def missing_tab(route):
                payload = route.fetch().json()
                payload["result"]["guitar_tab"] = {"source": "original", "status": "unavailable"}
                payload["result"]["separation"]["midi_stems"] = []
                route.fulfill(json=payload)
            page.route(f"**/api/jobs/{JOB}?include_notes=false", missing_tab)
            page.route(f"**/api/jobs/{JOB}/guitar-analysis", lambda route: route.fulfill(json={"status": "unavailable"}))
            page.goto("http://127.0.0.1:8788/")
            page.locator(f'[data-job="{JOB}"]').click()
            page.locator('[data-result-view="tab"]').click()
            page.locator("#generateGuitarTab").wait_for(state="visible")
            assert page.locator("#generateGuitarTab").is_enabled()
            assert "純吉他原音" in page.locator("#continuousTab").inner_text()
            # No POST is performed: restore real successful responses and reload.
            page.unroute_all(behavior="wait")
            page.reload()
            page.locator(f'[data-job="{JOB}"]').click()
            page.locator('[data-result-view="tab"]').click()
            page.locator("#continuousTab .tab-system").first.wait_for(state="visible")
            assert not page.locator("#generateGuitarTab").is_visible()
            assert page.evaluate("state.tabSource === 'guitar' && state.tabNotes.length > 0")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert not errors, errors
            page.screenshot(path=f"/tmp/chordlab-pure-guitar-{name}.png", full_page=True)
            print(name, "original-source missing-TAB button and recovered-TAB display passed", flush=True)
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
