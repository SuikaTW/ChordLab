"""Live queue/preview preservation check. Generation is explicit; never applies."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from dotenv import load_dotenv
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));load_dotenv(ROOT/'.env')
from app import main


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--job',default='d004a3af3f8246a7aaa3455235f64bbc')
    parser.add_argument('--generate',action='store_true')
    args=parser.parse_args();directory=main.JOBS/args.job
    raw={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (directory/'stem-midi').iterdir() if p.is_file()}
    with main.db() as c:
        private=[tuple(row) for row in c.execute('SELECT viewer,revision,document FROM user_tabs WHERE job_id=?',(args.job,))]
    base='http://127.0.0.1:8788'
    token=main.sign_session(main.USERNAME,'local',int(time.time())+600)
    with httpx.Client(base_url=base,cookies={main.COOKIE:token},timeout=30) as client:
        before=client.get(f'/api/jobs/{args.job}?include_notes=false').json()['result']
        if args.generate:
            response=client.post(f'/api/jobs/{args.job}/chord-review',headers={'Origin':base},json={'start':13,'end':51,'method':'event_verified'})
            assert response.status_code==202,response.text
        deadline=time.monotonic()+300;last=None
        while time.monotonic()<deadline:
            info=client.get(f'/api/jobs/{args.job}/chord-review').json()
            if info['status']!=last:print(info['status'],flush=True);last=info['status']
            if info['status']=='done':break
            assert info['status'] in {'queued','working'},info
            time.sleep(1)
        else:raise TimeoutError('Local review timeout')
        after=client.get(f'/api/jobs/{args.job}?include_notes=false').json()['result']
        assert after['methods']==before['methods'],'Preview must not publish any method'
        assert after.get('key')==before.get('key') and after.get('active_method')==before.get('active_method')
        assert info['summary']['version']==3 and info['request']=={'start':13.,'end':51.,'method':'event_verified'}
        for original in before['methods']['event_verified']:
            if original['end']<=13 or original['start']>=51 or original.get('manual'):
                assert original in info['chords'],'Outside/manual segment changed'
        assert len(info['chords'])<2000
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==checksum for p,checksum in raw.items())
    with main.db() as c:
        assert private==[tuple(row) for row in c.execute('SELECT viewer,revision,document FROM user_tabs WHERE job_id=?',(args.job,))]
    assert not list(directory.glob('.local-chord-review-*'))
    print('local dense recheck queued; original/Key/manual TAB/raw files preserved; proposal unapplied',flush=True)
    print(info['summary'],flush=True)


if __name__=='__main__':run()
