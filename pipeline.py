#!/usr/bin/env python3
"""Hourly cloud/Mac runner with atomic GitHub publication and per-firm CAS merging."""
import argparse,base64,concurrent.futures,json,os,pathlib,subprocess,time,uuid
import requests
from core import COLUMNS,csv_text,merge,now,validate
from collectors import REGISTRY,collect

REPO=os.environ.get('STAFFING_REPO','slimfrmdafo/staffing-job-feed')
BRANCH='feed'
class GitHub:
    def __init__(self):
        token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if not token:token=subprocess.check_output(['/usr/local/bin/gh','auth','token'],text=True).strip()
        self.s=requests.Session();self.s.headers.update(Authorization='Bearer '+token,Accept='application/vnd.github+json')
    def api(self,method,path,**kwargs):
        r=self.s.request(method,'https://api.github.com/repos/'+REPO+'/'+path,timeout=90,**kwargs)
        r.raise_for_status();return r.json() if r.content else {}
    def read(self):
        try:head=self.api('GET','git/ref/heads/'+BRANCH)['object']['sha']
        except requests.HTTPError as e:
            if e.response.status_code!=404:raise
            head=None
        if not head:return None,{'firms':{},'runs':[]}
        commit=self.api('GET','git/commits/'+head)
        tree=self.api('GET','git/trees/'+commit['tree']['sha'])
        entry=next((x for x in tree['tree'] if x['path']=='state.json'),None)
        if not entry:raise RuntimeError('Published branch exists without state; refusing data loss')
        blob=self.api('GET','git/blobs/'+entry['sha'])
        state=json.loads(base64.b64decode(blob['content']))
        return head,state
    def publish(self,attempts,run):
        for retry in range(10):
            head,state=self.read();state=merge(state,attempts)
            rows=sorted((r for f in state['firms'].values() for r in f['rows']),key=lambda r:(r['firm'],r['job_id']))
            if not rows and not head:raise RuntimeError('No successful non-empty first snapshot; refusing empty initial feed')
            state.setdefault('runs',[]).append(run);state['runs']=state['runs'][-240:];state['published_at']=now()
            content={'staffing_jobs.csv':csv_text(rows),'staffing_status.txt':status_text(state),'state.json':json.dumps(state,ensure_ascii=False,indent=2)}
            entries=[]
            for name,text in content.items():
                blob=self.api('POST','git/blobs',json={'content':text,'encoding':'utf-8'})
                entries.append({'path':name,'mode':'100644','type':'blob','sha':blob['sha']})
            payload={'tree':entries}
            if head:payload['base_tree']=self.api('GET','git/commits/'+head)['tree']['sha']
            tree=self.api('POST','git/trees',json=payload)
            commit=self.api('POST','git/commits',json={'message':f"{run['route']} snapshot {run['completed_at']}",'tree':tree['sha'],'parents':[head] if head else []})
            try:
                if head:self.api('PATCH','git/refs/heads/'+BRANCH,json={'sha':commit['sha'],'force':False})
                else:self.api('POST','git/refs',json={'ref':'refs/heads/'+BRANCH,'sha':commit['sha']})
                print('Published',len(rows),'rows; commit',commit['sha'],flush=True)
                return state,commit['sha']
            except requests.HTTPError as e:
                if e.response.status_code not in (409,422):raise
                time.sleep(1+retry)
        raise RuntimeError('Publication conflict retry budget exhausted; remote feed remains intact')

def status_text(state):
    lines=['Staffing job feed',f"Published UTC: {state['published_at']}",f'Repository: https://github.com/{REPO}',
           'Feed: https://raw.githubusercontent.com/'+REPO+'/feed/staffing_jobs.csv',
           'Rows are replaced only after a complete successful newer snapshot for that firm.',
           'Unavailable firms retain their last successful snapshot. Zero matching rows is a valid completed search.','']
    total=contracts=0
    for firm in REGISTRY:
        f=state['firms'].get(firm,{});rows=f.get('rows',[]);count=sum(r['job_type'] in ('contract','contract-to-hire') for r in rows);total+=len(rows);contracts+=count
        lines.append(f"{firm}: listings={len(rows)} contracts={count} snapshot_runner={f.get('snapshot_route','none')} last_success={f.get('completed_at','never')}")
        for route,a in sorted(f.get('attempts',{}).items()):
            lines.append(f"  {route}: {'OK' if a['ok'] else 'FAILED'} at {a['completed_at']} "+(str(a.get('info',{})) if a['ok'] else a.get('error','unknown error')))
    lines.extend(['',f'TOTAL listings={total} contracts={contracts}','', 'Recent unattended runs:'])
    for run in state.get('runs',[])[-8:]:lines.append(json.dumps(run,sort_keys=True))
    return '\n'.join(lines)+'\n'

def main():
    p=argparse.ArgumentParser();p.add_argument('--route',choices=['cloud','mac'],required=True);p.add_argument('--publish',action='store_true');p.add_argument('--firms',nargs='*');p.add_argument('--output',default='run-result.json');p.add_argument('--all',action='store_true');args=p.parse_args()
    os.environ['STAFFING_ROUTE']=args.route
    start=now();run_id=os.environ.get('GITHUB_RUN_ID') or str(uuid.uuid4());client=GitHub() if args.publish else None
    firms=args.firms or list(REGISTRY)
    if args.route=='mac' and not args.firms and not args.all:
        _,state=client.read() if client else (None,{'firms':{}})
        firms=[f for f in firms if state['firms'].get(f,{}).get('attempts',{}).get('cloud',{}).get('ok') is False]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:attempts=list(executor.map(lambda f:collect(f,args.route),firms))
    for a in attempts:
        if a['ok']:validate(a['rows'])
    run={'id':run_id,'route':args.route,'started_at':start,'completed_at':now(),'trigger':os.environ.get('GITHUB_EVENT_NAME','local'),'firms_attempted':len(attempts),'firms_succeeded':sum(a['ok'] for a in attempts),'firms_failed':sum(not a['ok'] for a in attempts)}
    pathlib.Path(args.output).write_text(json.dumps({'run':run,'attempts':attempts},ensure_ascii=False,indent=2))
    if client:client.publish(attempts,run)
    print(json.dumps(run),flush=True)

if __name__=='__main__':main()
