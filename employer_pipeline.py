#!/usr/bin/env python3
"""Hourly employer feed, isolated state and atomic publication beside staffing."""
import argparse,concurrent.futures,json,os,pathlib,uuid
from core import now,validate
from pipeline import GitHub,REPO
from employer_collectors import REGISTRY,PRIORITY,collect,refresh_known_missing

class EmployerGitHub(GitHub):
    state_file='employer_state.json'
    csv_file='employer_jobs.csv'
    status_file='employer_status.txt'
    def read(self):
        try:return super().read()
        except RuntimeError as e:
            if str(e)!='Published branch exists without state; refusing data loss':raise
            head=self.api('GET','git/ref/heads/feed')['object']['sha'];commit=self.api('GET','git/commits/'+head);tree=self.api('GET','git/trees/'+commit['tree']['sha'])
            names={x['path'] for x in tree['tree']}
            if self.csv_file in names:raise
            return head,{'firms':{},'runs':[]}
    def format_status(self,state):return status_text(state)

def status_text(state):
    lines=['Employer job feed',f"Published UTC: {state['published_at']}",f'Repository: https://github.com/{REPO}',
      f'Feed: https://raw.githubusercontent.com/{REPO}/feed/employer_jobs.csv',
      'Priority employers are attempted on every cloud run. Mac retries only employers whose latest cloud attempt failed.',
      'Only a complete successful newer pull replaces its own employer snapshot. Failures retain prior rows.',
      'Employer and staffing files have separate state; publications preserve both feeds.', '']
    total=contacts=0
    for name in list(PRIORITY)+[n for n in REGISTRY if n not in PRIORITY]:
        f=state.get('firms',{}).get(name,{});rows=f.get('rows',[]);total+=len(rows)
        contacts+=sum(any(r[k] for k in ('recruiter_name','recruiter_email','recruiter_phone')) for r in rows)
        runners='cloud+mac' if f.get('attempts',{}).get('cloud',{}).get('ok') is False else 'cloud'
        lines.append(f"{name}: listings={len(rows)} runners={runners} snapshot_runner={f.get('snapshot_route','none')} last_success={f.get('completed_at','never')}")
        for route,a in sorted(f.get('attempts',{}).items()):lines.append(f"  {route}: {'OK' if a['ok'] else 'FAILED'} at {a['completed_at']} "+(str(a.get('info',{})) if a['ok'] else a.get('error','unspecified')))
    lines+=['',f'TOTAL listings={total} posted_contacts={contacts}','Unknown optional fields remain empty. All included listings use full posting details.','', 'Recent run receipts:']
    lines.extend(json.dumps(r,sort_keys=True) for r in state.get('runs',[])[-10:]);return '\n'.join(lines)+'\n'

def preserve_unreadable_existing(attempt,state):
    hidden=set(attempt.get('info',{}).get('unpublished_index_ids',[]))
    prior={r['job_id'] for r in state.get('firms',{}).get(attempt['firm'],{}).get('rows',[])}
    if hidden & prior:
        attempt.update(ok=False,rows=[],error='Previously published jobs became ID-only/unreadable search entries; retaining complete prior employer snapshot: '+', '.join(sorted(hidden & prior)))

def main():
    p=argparse.ArgumentParser();p.add_argument('--route',choices=['cloud','mac'],required=True);p.add_argument('--publish',action='store_true');p.add_argument('--firms',nargs='*');p.add_argument('--output',default='employer-run-result.json');p.add_argument('--all',action='store_true');args=p.parse_args()
    start=now();run_id=os.environ.get('GITHUB_RUN_ID') or str(uuid.uuid4());client=EmployerGitHub() if args.publish else None
    trigger=os.environ.get('EMPLOYER_TRIGGER') or os.environ.get('GITHUB_EVENT_NAME','local');timer=os.environ.get('EMPLOYER_TIMER_RUN_ID','')
    if args.route=='cloud' and timer:trigger='cloud_clock'
    state=client.read()[1] if client else {'firms':{}}
    if timer and any(r.get('timer_run_id')==timer and r.get('route')=='cloud' for r in state.get('runs',[])):print('Timer already published; skipped duplicate');return
    firms=args.firms or list(PRIORITY)+[f for f in REGISTRY if f not in PRIORITY]
    if args.route=='mac' and not args.firms and not args.all:firms=[f for f in firms if state['firms'].get(f,{}).get('attempts',{}).get('cloud',{}).get('ok') is False]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:attempts=list(pool.map(lambda f:collect(f,args.route),firms))
    for a in attempts:
        try:refresh_known_missing(a,state.get('firms',{}).get(a['firm'],{}))
        except Exception as e:a.update(ok=False,rows=[],error='Known-job full-detail refresh failed; retaining previous employer snapshot: '+str(e))
        preserve_unreadable_existing(a,state)
        if a['ok']:validate(a['rows'])
    run={'id':run_id,'route':args.route,'started_at':start,'completed_at':now(),'trigger':trigger,'firms_attempted':len(attempts),'firms_succeeded':sum(a['ok'] for a in attempts),'firms_failed':sum(not a['ok'] for a in attempts)}
    if timer:run.update(timer_run_id=timer,timer_fired_at=os.environ.get('EMPLOYER_TIMER_FIRED_AT',''))
    pathlib.Path(args.output).write_text(json.dumps({'run':run,'attempts':attempts},ensure_ascii=False,indent=2))
    if client:
        if not any(a['ok'] and a['rows'] for a in attempts) and not any(f.get('rows') for f in state['firms'].values()):raise RuntimeError('First employer publication needs a successful nonempty full snapshot')
        client.publish(attempts,run)
    print(json.dumps(run),flush=True)
if __name__=='__main__':main()
