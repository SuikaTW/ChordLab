"""Playback/voicing controls, isolated catalog only; no real analysis mutations."""
from playwright.sync_api import sync_playwright

JOB = "d0a3f98491a64544a5a86c568dc9ffef"


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/google/chrome/chrome",headless=True,args=["--no-sandbox"])
        for name,width in (("desktop",1365),("mobile",390),("small-mobile",320)):
            context = browser.new_context(viewport={"width":width,"height":900},is_mobile=width<500,has_touch=width<500)
            page = context.new_page()
            errors = []
            page.on("pageerror",lambda error: errors.append(str(error)))
            page.goto("http://127.0.0.1:8790/login")
            page.locator('[name="username"]').fill("browser-test")
            page.locator('[name="password"]').fill("local-browser-test-password")
            page.locator('button[type="submit"]').click()
            page.locator(f'[data-job="{JOB}"]').click()
            page.locator("#timeline .chord-block").first.wait_for()
            page.locator("#practiceTools summary").click()
            page.locator("#playbackSpeed").select_option("0.75")
            assert page.evaluate("document.querySelector('#audioPlayer').playbackRate") == .75
            assert page.evaluate("document.querySelector('#audioPlayer').preservesPitch")
            page.wait_for_function("() => document.querySelector('#audioPlayer').readyState >= 1")
            page.evaluate("document.querySelector('#audioPlayer').currentTime=2")
            page.locator("#loopA").click()
            page.evaluate("document.querySelector('#audioPlayer').currentTime=4")
            page.locator("#loopB").click()
            page.locator("#loopToggle").click()
            assert page.evaluate("Practice.inspect().enabled")
            page.locator("#playToggle").click()
            page.wait_for_function("() => !document.querySelector('#audioPlayer').paused")
            page.evaluate("document.querySelector('#audioPlayer').currentTime=4.1")
            page.wait_for_function("() => document.querySelector('#audioPlayer').currentTime < 3")
            page.locator("#playToggle").click()
            page.locator("#loopClear").click()
            assert not page.evaluate("Practice.inspect().enabled")
            page.locator("#timeline .chord-block").nth(1).click()
            page.locator("#loopChord").click()
            assert page.evaluate("Practice.inspect().enabled")
            page.locator("#smoothVoicings").check()
            assert page.locator("#voicingPositions [aria-pressed=true]").count() == 1
            page.locator("#capoSelect").select_option("2")
            assert page.locator(".chord-chart").is_visible()
            assert page.locator("#voicingPositions [aria-pressed=true]").count() == 1
            # Synthetic response exercises new-engine UI without writing media.
            def notes_response(route):
                response = context.request.get(f"http://127.0.0.1:8790/api/jobs/{JOB}/notes/guitar")
                payload = response.json()
                payload.update(profile="guitar_verified_v1",refinement={"reviewed_notes":100,"changed_notes":2,"uncertain_notes":3,"calibrated_pitches":0})
                route.fulfill(json=payload)
            page.route(f"**/api/jobs/{JOB}/notes/guitar?engine=verified",notes_response)
            page.route(f"**/api/jobs/{JOB}/guitar-analysis?engine=verified",lambda route: route.fulfill(json={"status":"done","variants":[{"engine":"verified","available":True,"ready":True}]}))
            page.evaluate("state.current.result.guitar_tab.variants ||= {}; state.current.result.guitar_tab.variants.verified={status:'done'}")
            page.locator('[data-result-view="tab"]').click()
            page.locator("#tabEngineOption summary").click()
            page.locator("#tabEngine").select_option("verified")
            page.locator("#verificationSummary").wait_for()
            assert "調整 2 音" in page.locator("#verificationSummary").inner_text()
            assert page.locator("#verificationPreviewPanel").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+1")
            # Changing songs clears the range, but retains the selected speed.
            page.locator('[data-job="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]').click()
            page.wait_for_function("() => state.current?.id === 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'")
            assert not page.evaluate("Practice.inspect().enabled")
            assert page.evaluate("document.querySelector('#audioPlayer').playbackRate") == .75
            assert not errors,errors
            print(name,"speed/loop/voicings/verification/switching passed",flush=True)
            context.close()
        browser.close()


if __name__ == "__main__": run()
