"""Read-only browser workflow; local review/apply/save writes are intercepted."""
import copy
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));load_dotenv(ROOT/'.env')
from app import main

BASE='http://127.0.0.1:8788'
JOB='d004a3af3f8246a7aaa3455235f64bbc'


def run():
    token=main.sign_session(main.USERNAME,'local',int(time.time())+3600)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/opt/google/chrome/chrome',headless=True,args=['--no-sandbox'])
        for width in (1365,390,320):
            context=browser.new_context(viewport={'width':width,'height':900},is_mobile=width<500,has_touch=width<500)
            context.add_cookies([{'name':main.COOKIE,'value':token,'url':BASE}])
            original=context.request.get(f'{BASE}/api/jobs/{JOB}?include_notes=false').json()
            updated=copy.deepcopy(original)
            updated['result']['methods']['local_review']=[dict(start=0,end=2,chord='C'),dict(start=2,end=5,chord='Am'),dict(start=5,end=original['duration'],chord='C')]
            updated['result']['active_method']='local_review'
            state={'phase':'pending','applied':False};calls=[];errors=[]
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            def intercept(route):
                request=route.request;url=request.url
                if url.endswith('/chord-review/apply'):
                    assert request.method=='POST';state['applied']=True
                    route.fulfill(json={'ok':True,'method':'local_review'});return
                if url.endswith('/chord-review'):
                    if request.method=='POST':
                        calls.append(request.post_data_json);state['phase']='done'
                        route.fulfill(status=202,json={'status':'queued'});return
                    payload={'status':state['phase']}
                    if state['phase']=='done':
                        payload.update(request={'start':2,'end':5,'method':'event_verified'},method='event_verified',
                            chords=updated['result']['methods']['local_review'],summary={'changed_segments':1})
                    route.fulfill(json=payload);return
                if f'/api/jobs/{JOB}?include_notes=false' in url and state['applied']:
                    route.fulfill(json=updated);return
                if request.method not in {'GET','HEAD'}:raise AssertionError('Unexpected live mutation: '+url)
                route.continue_()
            page.route('**/api/**',intercept)
            page.goto(BASE);page.wait_for_function('() => state.current && state.jobs.length')
            page.evaluate('(id)=>openJob(id)',JOB)
            page.locator('#localChordReviewPanel summary').click()
            page.locator('#reviewStart').fill('2');page.locator('#reviewEnd').fill('5')
            page.locator('#reviewChords').click()
            page.locator('#applyChordReview').wait_for(state='visible')
            assert calls==[{'start':2,'end':5,'method':'event_verified'}]
            page.locator('#localChordReviewCandidates button').first.click()
            loop=page.evaluate('Practice.inspect()')
            assert loop['first']==2 and loop['last']==5 and loop['enabled']
            page.once('dialog',lambda dialog:dialog.accept())
            page.locator('#applyChordReview').click()
            page.wait_for_function('() => state.method === "local_review"')
            assert page.evaluate('state.current.result.key')==original['result']['key']
            assert page.evaluate('state.current.result.methods.chordino')==original['result']['methods']['chordino']
            page.evaluate('(id)=>openJob(id)',JOB)
            assert page.evaluate('state.method')=='local_review','Explicit local selection has priority after reopen'
            page.locator('[data-result-view="tab"]').click()
            page.locator('#continuousTab [data-note-index]').first.wait_for()
            page.locator('.tab-options summary').click()
            page.locator('#tabRole').select_option('melody')
            page.wait_for_function('() => document.querySelector("#continuousTab").getAttribute("aria-busy") !== "true"')
            assert page.locator('#tabRole').input_value()=='melody'
            page.locator('#tabEditMode').check()
            page.locator('#continuousTab [data-note-index]').first.click()
            page.locator('#tabEditTechnique').select_option('slide')
            page.locator('#tabNoteForm button[type="submit"]').click()
            assert page.locator('#tabSave').is_enabled()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            assert not errors,errors
            print(width,'local recheck/loop/confirm/original/Key/role/technique/mobile passed',flush=True)
            context.close()
        browser.close()


if __name__=='__main__':run()
