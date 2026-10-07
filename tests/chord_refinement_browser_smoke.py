"""Live read-only smoke; --generate explicitly queues missing chord v2 versions."""
from pathlib import Path
import argparse
import copy
import hashlib
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from app import main
import httpx
from playwright.sync_api import sync_playwright

JOBS = ("cb4455ee4bce40b3974383fb393d835d", "d0a3f98491a64544a5a86c568dc9ffef")


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    base = "http://127.0.0.1:8788"
    token = main.sign_session(main.USERNAME, "local", int(time.time()) + 1800)
    with httpx.Client(base_url=base, cookies={main.COOKIE: token}, timeout=30) as client:
        for job in JOBS:
            before = client.get(f"/api/jobs/{job}?include_notes=false").json()["result"]
            expected = copy.deepcopy(before["methods"])
            expected.pop("chord_v2", None)
            files = [main.JOBS / job / name for name in ("chordino.json", "basic_pitch.json", "btc.json")]
            hashes = [hashlib.sha256(file.read_bytes()).hexdigest() for file in files if file.is_file()]
            if args.generate:
                response = client.post(f"/api/jobs/{job}/chord-refinement", headers={"Origin": base})
                assert response.status_code == 202, response.text
            deadline = time.monotonic() + 700
            previous = None
            while True:
                response = client.get(f"/api/jobs/{job}/chord-refinement")
                response.raise_for_status()
                status = response.json()["status"]
                if status != previous:
                    print(job, status, flush=True)
                    previous = status
                if status == "done":
                    break
                assert args.generate and status in {"queued", "working"} and time.monotonic() < deadline, response.text
                time.sleep(2)
            after = client.get(f"/api/jobs/{job}?include_notes=false").json()["result"]
            remaining = copy.deepcopy(after["methods"])
            refined = remaining.pop("chord_v2")
            assert remaining == expected
            assert after["active_method"] == before["active_method"] and after["key"] == before["key"]
            assert hashes == [hashlib.sha256(file.read_bytes()).hexdigest() for file in files if file.is_file()]
            assert refined and all(s["end"] > s["start"] for s in refined)
            assert all(abs(a["end"]-b["start"]) <= .002 for a, b in zip(refined, refined[1:]))
            print("v2 segments", len(refined), "metadata", after["chord_refinement"], flush=True)
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
            page.locator(f'[data-job="{JOBS[0]}"]').click()
            page.locator(".method-options summary").click()
            page.locator('[data-method="chord_v2"]').click()
            assert "實驗版" in page.locator("#comparisonSummary").inner_text()
            assert page.locator("#timeline .chord-block").count() > 0
            assert not page.locator("#buildChordV2").is_visible()
            marked = page.locator("#timeline .needs-review")
            if marked.count():
                marked.first.click()
                assert "不是正確率" in page.locator("#chordCandidates").inner_text()
            page.locator("#capoSelect").select_option("2")
            page.locator('[data-method="chordino"]').click()
            assert page.locator("#comparisonSummary").is_hidden()
            page.locator('[data-method="chord_v2"]').click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert not errors, errors
            page.screenshot(path=f"/tmp/chordlab-refinement-{name}.png", full_page=True)
            print(name, "v2/baseline/capo/candidates/viewport passed", flush=True)
            # Mock only this browser's API responses: exercise missing/queued/
            # ready controls without editing or reprocessing a live song.
            phase = {"submitted": False, "checks": 0, "done": False}
            def job_response(route):
                response = route.fetch()
                payload = response.json()
                if not phase["done"]:
                    payload["result"]["methods"].pop("chord_v2", None)
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
                        "busy_engine": None if status == "pending" else "chord_v2"})
            page.route(f"**/api/jobs/{JOBS[0]}?include_notes=false", job_response)
            page.route(f"**/api/jobs/{JOBS[0]}/chord-refinement", task_response)
            page.reload()
            page.locator(f'[data-job="{JOBS[0]}"]').click()
            page.locator("#buildChordV2").wait_for(state="visible")
            page.locator("#buildChordV2").click()
            page.wait_for_function("() => document.querySelector('#buildChordV2').disabled && document.querySelector('#buildChordV2').textContent.includes('排隊')")
            page.wait_for_function("() => state.current?.result?.methods?.chord_v2?.length > 0", timeout=20000)
            assert page.locator("#buildChordV2").is_hidden()
            assert phase["done"] and not errors, errors
            print(name, "missing/submit/queue/completion controls passed (mock responses)", flush=True)
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
