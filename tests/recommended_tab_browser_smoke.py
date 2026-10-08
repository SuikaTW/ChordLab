"""Read-only recommendation UI checks; all generation requests are intercepted."""
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from app import main
from app.guitar_engines import recommendation_current
import json

BASE = "http://127.0.0.1:8788"
def current_recommendation():
    with main.db() as connection:
        rows = connection.execute("SELECT id,owner,is_public,result FROM jobs WHERE status='done' ORDER BY updated_at DESC").fetchall()
    return next((row['id'] for row in rows if (row['owner'] == main.USERNAME or row['is_public']) and row['result'] and
                 recommendation_current(main.JOBS / row['id'], json.loads(row['result']))), None)


JOB = current_recommendation()


def run():
    if not JOB:
        raise RuntimeError("目前沒有可讀取且仍有效的建議譜可供瀏覽器冒煙測試")
    token = main.sign_session(main.USERNAME, "local", int(time.time()) + 1800)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/google/chrome/chrome", args=["--no-sandbox"])
        for width in (1365, 390, 320):
            context = browser.new_context(viewport={"width": width, "height": 900},
                is_mobile=width < 500, has_touch=width < 500)
            context.add_cookies([{"name": main.COOKIE, "value": token, "url": BASE}])
            page = context.new_page()
            errors, posts = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            personal = {"document": None, "revision": 0, "reference_confirmed": False}
            page.route(f"**/api/jobs/{JOB}/tab?instrument=guitar",
                lambda route: route.fulfill(json=personal))
            def guard_post(route):
                if route.request.method == "POST":
                    posts.append(route.request.url)
                    route.fulfill(status=202, json={"status": "queued"})
                else:
                    route.continue_()
            page.route(f"**/api/jobs/{JOB}/guitar-analysis?engine=*", guard_post)
            page.goto(BASE)
            # The song may be beyond the first page of the library.
            page.evaluate("(id) => openJob(id, false, true)", JOB)
            page.locator('[data-result-view="tab"]').click()
            page.wait_for_function("() => state.tabEngine === 'event_verified' && TabStudio.inspect().count > 0")
            assert not page.locator("#tabEngineOption").evaluate("e => e.open")
            assert not page.locator("#tabEngine").is_visible()
            assert page.locator("#recommendedTab").inner_text() == "查看建議譜"
            page.evaluate("""() => {
                const control = document.querySelector('#tabEngine');
                control.value = 'basic_pitch';
                control.dispatchEvent(new Event('change', { bubbles: true }));
            }""")
            page.wait_for_function("() => state.tabEngine === 'basic_pitch' && TabStudio.inspect().count > 0")
            page.evaluate("""() => {
                const control = document.querySelector('#tabEngine');
                control.value = 'event_verified';
                control.dispatchEvent(new Event('change', { bubbles: true }));
            }""")
            page.wait_for_function("() => state.tabEngine === 'event_verified' && TabStudio.inspect().count > 0")
            assert page.locator("#tabEngineMidi").get_attribute("href").endswith("event_verified")
            assert not posts, "Viewing ready recommendations must not generate"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

            # A private manual score wins over an automatic recommendation.
            personal.update(revision=1, document={"revision": 1, "instrument": "guitar",
                "source_engine": "basic_pitch", "tuning": "standard", "capo": 0,
                "voice": "all", "position": "auto", "density": "full", "fingering_mode": "playable",
                "rhythm": {"bpm": 120, "meter": 4, "offset": 0, "manual": False},
                "notes": [{"index": 0, "start": .4, "end": 1, "midi": 64, "string": 5,
                    "fret": 0, "velocity": .7, "edited": True}]})
            page.evaluate("id => openJob(id)", JOB)
            page.locator('[data-result-view="tab"]').click()
            page.wait_for_function("() => state.tabEngine === 'basic_pitch' && TabStudio.inspect().count === 1")
            page.locator(".tab-options summary").click()
            page.locator("#tabBpm").fill("141")
            page.locator("#tabBpm").dispatch_event("change")
            assert page.evaluate("TabStudio.inspect().dirty")
            page.once("dialog", lambda dialog: dialog.dismiss())
            page.locator("#recommendedTab").click()
            assert page.evaluate("state.tabEngine === 'basic_pitch' && TabStudio.inspect().dirty")
            assert not posts and not errors, (posts, errors)
            print(width, "primary recommendation, no redundant generation, private-score priority and edit guard passed", flush=True)
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
