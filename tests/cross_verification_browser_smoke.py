"""Read-only live cross-check UI, preview and independent chord-method regression."""
import sys
import argparse
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); load_dotenv(ROOT/".env")
from app import main
BASE="http://127.0.0.1:8788"
JOB="cb4455ee4bce40b3974383fb393d835d"


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument("--engine",choices=["cross_verified","event_verified"],default="cross_verified")
    engine=parser.parse_args().engine
    token=main.sign_session(main.USERNAME,"local",int(time.time())+3600)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path="/opt/google/chrome/chrome",headless=True,args=["--no-sandbox"])
        for name,width in (("desktop",1365),("mobile",390),("small-mobile",320)):
            context=browser.new_context(viewport={"width":width,"height":900},is_mobile=width<500,has_touch=width<500)
            context.add_cookies([{"name":main.COOKIE,"value":token,"url":BASE}])
            page=context.new_page(); errors=[]
            page.on("pageerror",lambda error: errors.append(str(error)))
            page.goto(BASE)
            page.locator(f'[data-job="{JOB}"]').click()
            page.locator('[data-result-view="tab"]').click()
            page.locator("#tabEngineOption summary").click()
            page.locator("#tabEngine").select_option(engine)
            page.locator("#verificationSummary").wait_for()
            assert "3 個音符模型" in page.locator("#verificationSummary").inner_text()
            assert page.locator("#tabEngineMidi").get_attribute("href").endswith(engine)
            if engine=="event_verified":
                assert "補" in page.locator("#verificationSummary").inner_text()
                page.evaluate("async () => {Object.assign(state.tabEventReview,{adjusted_offsets:4,retrigger_splits:2,suggestions:[{kind:'uncertain_addition',start:3}]}); await TabStudio.render();}")
                assert '音長 4／重撥 2' in page.locator('#verificationSummary').inner_text()
                page.locator("#eventReviewPanel summary").click()
                assert '補音證據不足' in page.locator('#eventReviewCandidates button').first.inner_text()
                page.locator("#eventReviewCandidates button").first.click()
                assert abs(page.locator("#audioPlayer").evaluate("p=>p.currentTime")-2.8)<.05
            page.locator("#continuousTab .tab-system").first.wait_for()
            page.locator("#verificationPreviewPanel summary").click()
            page.locator("#playVerification").click()
            page.wait_for_function("() => !document.querySelector('#verificationPlayer').paused")
            assert f"engine={engine}" in page.locator("#verificationPlayer").get_attribute("src")
            page.locator('[data-result-view="chords"]').click()
            page.locator(".method-options summary").click()
            page.locator(f'[data-method="{engine}"]').click()
            assert ("建議版" if engine=="event_verified" else "交叉校驗") in page.locator("#comparisonSummary").inner_text()
            page.locator("#timeline .chord-block").nth(1).click()
            page.locator(".chord-chart").wait_for()
            page.locator("#capoSelect").select_option("2")
            assert "原和弦" in page.locator("#selectedChord").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+1")
            worker=page.evaluate("""() => new Promise((resolve,reject) => {
              const w=new Worker('/static/tab-worker.js?v=10');
              w.onmessage=e=>{w.terminate();resolve(e.data)};
              w.onerror=e=>{w.terminate();reject(new Error(e.message))};
              w.postMessage({notes:[{start:0,end:.5,midi:64,velocity:.7}],options:{position:'high'}});
            })""")
            assert worker["result"]["notes"][0]["fret"]==0, "Worker must use the open-string fix, not cached v7"
            phrase=page.evaluate("""() => new Promise((resolve,reject) => {
              const w=new Worker('/static/tab-worker.js?v=10');
              w.onmessage=e=>{w.terminate();resolve(e.data)};
              w.onerror=e=>{w.terminate();reject(new Error(e.message))};
              w.postMessage({notes:[{start:0,end:1.5,midi:64,velocity:.7},{start:.2,end:.38,midi:65,velocity:.7},{start:.4,end:.8,midi:67,velocity:.7}],options:{}});
            })""")
            assert len(phrase['result']['notes'])==3 and phrase['result']['notes'][0]['end']==1.5, 'Live worker must preserve the open sustain'
            # Simulate disagreement to exercise candidate/marker controls without a save.
            page.evaluate("const s=chords()[state.selected]; s.refinement={uncertain:true,alternatives:[{chord:'Am',share:1}],source:'cross_verified'}; renderTimeline(); renderEditor();")
            assert page.locator("#chordCandidates").is_visible()
            assert page.locator("#timeline .needs-review").count()>=1
            assert not errors,errors
            print(name,engine,"TAB/chords/candidates/preview/capo/viewport passed",flush=True)
            context.close()
        browser.close()


if __name__=="__main__": run()
