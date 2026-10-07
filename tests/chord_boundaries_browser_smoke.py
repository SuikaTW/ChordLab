"""Read-only regression for the reported long-chord ranges and selected exports."""
import argparse
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));load_dotenv(ROOT/'.env')
from app import main

BASE='http://127.0.0.1:8788'


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--job',default='d004a3af3f8246a7aaa3455235f64bbc')
    job=parser.parse_args().job
    token=main.sign_session(main.USERNAME,'local',int(time.time())+3600)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
        for width in (1365,390,320):
            context=browser.new_context(viewport={'width':width,'height':900},is_mobile=width<500,has_touch=width<500)
            context.add_cookies([{'name':main.COOKIE,'value':token,'url':BASE}])
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            # Reject any unexpected mutation; opening and comparing need none.
            page.route('**/api/**',lambda route:route.abort() if route.request.method not in {'GET','HEAD'} else route.continue_())
            page.goto(BASE)
            page.wait_for_function('() => state.current && state.jobs.length')
            page.evaluate('(id)=>openJob(id)',job)
            page.locator('[data-result-view="chords"]').click()
            assert page.evaluate('state.method')=='event_verified'
            for start,end in ((13.2,29),(32.7,51)):
                labels=page.evaluate('([a,b])=>[...new Set(chords().filter(s=>s.start<b&&s.end>a).map(s=>s.chord))]',[start,end])
                assert len(labels)>1,(start,end,labels)
            assert '細分' in page.locator('#comparisonSummary').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            response=context.request.get(f'{BASE}/api/jobs/{job}/export/chordpro?method=event_verified&capo=0')
            assert response.ok and 'event_verified' in response.text() and '[Ab]' in response.text()
            # A harmless attachment keeps the workspace loaded while testing
            # the actual link; do not save the download or mutate job media.
            page.route('**/export/chordpro*',lambda route:route.fulfill(status=200,
                headers={'Content-Type':'text/plain','Content-Disposition':'attachment; filename="test.cho"'},body='test'))
            page.locator('#exportToggle').click()
            with page.expect_request('**/export/chordpro*') as exported:
                with page.expect_download():
                    page.locator('[data-export="chordpro"]').click()
            assert 'method=event_verified' in exported.value.url
            page.evaluate("switchMethod('ensemble',false)")
            assert page.evaluate("chords().filter(s=>s.start<29&&s.end>13.2).every(s=>s.chord==='Eb')")
            # Simulate an existing manual active version only in the response.
            def manual_response(route):
                response=route.fetch();payload=response.json()
                payload['result']['active_method']='chordino'
                payload['result']['methods']['chordino'][0]['manual']=True
                route.fulfill(response=response,json=payload)
            page.route(f'**/api/jobs/{job}?include_notes=false',manual_response)
            page.evaluate('(id)=>openJob(id)',job)
            assert page.evaluate('state.method')=='chordino'
            assert not errors,errors
            print(width,'recommended/local changes/original/manual priority/export/viewport passed',flush=True)
            context.close()
        browser.close()


if __name__=='__main__':run()
