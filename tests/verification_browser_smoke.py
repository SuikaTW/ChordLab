"""Read-only live verification preview and switching regression."""
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
load_dotenv(ROOT/".env")
from app import main

JOB = "cb4455ee4bce40b3974383fb393d835d"
BASE = "http://127.0.0.1:8788"


def run():
    token = main.sign_session(main.USERNAME,"local",int(time.time())+3600)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/google/chrome/chrome",headless=True,args=["--no-sandbox"])
        for name,width in (("desktop",1365),("mobile",390)):
            context = browser.new_context(viewport={"width":width,"height":900},is_mobile=width<500,has_touch=width<500)
            context.add_cookies([{"name":main.COOKIE,"value":token,"url":BASE}])
            page = context.new_page()
            errors = []
            page.on("pageerror",lambda error: errors.append(str(error)))
            page.goto(BASE)
            page.locator(f'[data-job="{JOB}"]').click()
            page.locator('[data-result-view="tab"]').click()
            page.locator("#tabEngineOption summary").click()
            page.locator("#tabEngine").select_option("verified")
            page.locator("#verificationSummary").wait_for()
            page.locator("#continuousTab .tab-system").first.wait_for()
            assert "調整 8 音" in page.locator("#verificationSummary").inner_text()
            assert page.locator("#tabEngineMidi").get_attribute("href").endswith("verified")
            page.locator("#practiceTools summary").click()
            page.locator("#playbackSpeed").select_option("0.75")
            page.wait_for_function("() => document.querySelector('#audioPlayer').readyState >= 1")
            page.evaluate("document.querySelector('#audioPlayer').currentTime=10")
            page.locator("#verificationPreviewPanel summary").click()
            page.locator("#playVerification").click()
            page.wait_for_function("() => !document.querySelector('#verificationPlayer').paused")
            assert page.evaluate("document.querySelector('#audioPlayer').paused")
            assert page.evaluate("document.querySelector('#verificationPlayer').playbackRate") == .75
            assert 9 <= page.evaluate("document.querySelector('#verificationPlayer').currentTime") <= 12
            page.locator("#playToggle").click()
            page.wait_for_function("() => !document.querySelector('#audioPlayer').paused && document.querySelector('#verificationPlayer').paused")
            page.locator("#playToggle").click()
            page.locator("#tabEngine").select_option("hybrid")
            page.wait_for_function("() => state.tabProfile === 'guitar_hybrid_v2'")
            assert page.locator("#verificationPreviewPanel").is_hidden()
            assert page.locator("#verificationSummary").is_hidden()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+1")
            assert not errors,errors
            print(name,"live verification/playback exclusivity/speed/source switching passed",flush=True)
            context.close()
        browser.close()


if __name__ == "__main__": run()
