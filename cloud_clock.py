"""An unattended hourly relay using GitHub's server-side environment wait timer.

Each tiny tick launches a collector and queues its successor. GitHub waits 60
minutes without allocating a runner. No long-lived credential or Mac dispatcher.
"""
import json,os,time,urllib.request,urllib.error
from datetime import datetime,timezone
BASE='https://api.github.com/repos/'+os.environ.get('GITHUB_REPOSITORY','slimfrmdafo/staffing-job-feed')+'/'

def api(method,path,payload=None):
    data=json.dumps(payload).encode() if payload is not None else None
    headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json'}
    for n in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE+path,data=data,headers=headers,method=method),timeout=30) as response:
                body=response.read();return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            if error.code not in (429,500,502,503,504) or n==5:raise
        except (urllib.error.URLError,TimeoutError):
            if n==5:raise
        time.sleep(min(2**n,30))

def tick(call=api,run_id=None):
    run_id=run_id or os.environ['GITHUB_RUN_ID']
    if call('GET','actions/workflows/clock.yml')['state']!='active':
        print('Cloud clock is paused; no successor or collector launched.',flush=True);return
    stamp=datetime.now(timezone.utc).isoformat()
    # Queue renewal first, so an independent collector-dispatch error cannot stop the clock.
    call('POST','actions/workflows/clock.yml/dispatches',{'ref':'main','inputs':{'start_now':'false'}})
    print('Queued the next server-side 60-minute tick.',flush=True)
    call('POST','actions/workflows/collect.yml/dispatches',{'ref':'main','inputs':{'timer_run_id':str(run_id),'timer_fired_at':stamp}})
    print(json.dumps({'timer_run_id':str(run_id),'timer_fired_at':stamp,'collector_dispatched':True}),flush=True)

if __name__=='__main__':tick()
