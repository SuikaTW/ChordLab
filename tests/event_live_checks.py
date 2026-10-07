"""Live preservation and artifact checks. Generation is explicit --generate."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from dotenv import load_dotenv
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));load_dotenv(ROOT/".env")
from app import main

def run():
    parser=argparse.ArgumentParser()
    parser.add_argument("--job",default="cb4455ee4bce40b3974383fb393d835d")
    parser.add_argument("--generate",action="store_true")
    args=parser.parse_args();directory=main.JOBS/args.job
    baseline={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (directory/"stem-midi").iterdir()
              if p.is_file() and not p.name.startswith("guitar-event-verified")}
    with main.db() as connection:
        private_before=[tuple(row) for row in connection.execute("SELECT viewer,revision,document FROM user_tabs WHERE job_id=?",(args.job,))]
    base="http://127.0.0.1:8788"
    token=main.sign_session(main.USERNAME,"local",int(time.time())+3600)
    with httpx.Client(base_url=base,cookies={main.COOKIE:token},timeout=30) as client:
        before=client.get(f"/api/jobs/{args.job}?include_notes=false").json()["result"]
        if args.generate:
            response=client.post(f"/api/jobs/{args.job}/guitar-analysis?engine=event_verified",headers={"Origin":base})
            assert response.status_code==202,response.text
        deadline=time.monotonic()+600;last=None
        while time.monotonic()<deadline:
            status=client.get(f"/api/jobs/{args.job}/guitar-analysis?engine=event_verified").json()["status"]
            if status!=last: print(args.job,status,flush=True);last=status
            if status=="failed": raise AssertionError("Event worker failed")
            if status=="done": break
            time.sleep(1)
        else: raise TimeoutError("Event worker timeout")
        current=client.get(f"/api/jobs/{args.job}?include_notes=false").json()["result"]
        assert all(current["methods"][name]==segments for name,segments in before["methods"].items() if name!="event_verified")
        assert current.get("key")==before.get("key") and current.get("active_method")==before.get("active_method")
        payload=client.get(f"/api/jobs/{args.job}/notes/guitar?engine=event_verified").json()
        assert payload["profile"]=="guitar_event_verified_v1" and payload["note_count"]==len(payload["notes"])
        if args.generate:
            assert payload['recommendation']['revision']==main.RECOMMENDATION_REVISION
            assert payload['event_review']['version']==2
        assert client.get(f"/api/jobs/{args.job}/guitar-midi/event_verified").content.startswith(b"MThd")
        preview=client.get(f"/api/jobs/{args.job}/verification-preview?engine=event_verified",headers={"Range":"bytes=0-31"})
        assert preview.status_code==206 and preview.content.startswith(b"RIFF")
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==checksum for p,checksum in baseline.items())
    with main.db() as connection:
        assert [tuple(row) for row in connection.execute("SELECT viewer,revision,document FROM user_tabs WHERE job_id=?",(args.job,))]==private_before
    print(args.job,"raw files/manual versions/chords/Key preserved; MIDI and seekable preview passed",flush=True)
    print({k:payload["event_review"].get(k) for k in ("added_notes","adjusted_onsets","adjusted_offsets","retrigger_splits","uncertain_additions","review_candidates","original_mix_checked")},flush=True)

if __name__=="__main__": run()
