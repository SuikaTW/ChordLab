"""Run against guitar_preview_server.py, never the production catalog."""
from playwright.sync_api import sync_playwright

JOB = "d0a3f98491a64544a5a86c568dc9ffef"


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/google/chrome/chrome", headless=True,
                                    args=["--no-sandbox"])
        for name, width, height in (("desktop", 1365, 900), ("mobile", 390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height},
                                         is_mobile=name == "mobile", has_touch=name == "mobile")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto("http://127.0.0.1:8790/login")
            page.locator('[name="username"]').fill("browser-test")
            page.locator('[name="password"]').fill("local-browser-test-password")
            page.locator('button[type="submit"]').click()
            page.locator(f'[data-job="{JOB}"]').click()
            page.locator(".method-options summary").click()
            page.locator('[data-method="ensemble"]').click()
            page.locator('#timeline .needs-review').first.wait_for()
            assert "不同判斷" in page.locator("#comparisonSummary").inner_text()
            marked = page.locator('#timeline .needs-review')
            for i in range(marked.count()):
                marked.nth(i).click()
                if page.locator("#chordCandidates button").count():
                    break
            assert page.locator("#chordCandidates").is_visible()
            assert "占此段" in page.locator("#chordCandidates").inner_text()
            page.locator("#capoSelect").select_option("2")
            assert page.locator("#chordCandidates").is_visible()
            page.screenshot(path=f"/tmp/chordlab-btc-{name}.png", full_page=True)
            page.once("dialog", lambda dialog: dialog.accept())
            with page.expect_response(lambda r: r.request.method == "PUT" and "/chords" in r.url) as saved:
                page.locator("#chordCandidates button").first.click()
            assert saved.value.status == 200
            response = context.request.get(f"http://127.0.0.1:8790/api/jobs/{JOB}")
            result = response.json()["result"]
            assert result["active_method"] == "ensemble"
            assert any(s.get("manual") for s in result["methods"]["ensemble"])
            assert all(not s.get("manual") for s in result["methods"]["chordino"])
            page.reload()
            page.locator(f'[data-job="{JOB}"]').click()
            page.locator(".method-options summary").click()
            assert page.locator('[data-method="ensemble"]').is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert not errors, errors
            print(name, "candidate/capo/save/reload/viewport passed", flush=True)
            context.close()
        browser.close()


if __name__ == "__main__":
    run()
