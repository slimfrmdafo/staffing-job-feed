import csv,io,requests
from core import merge
from pipeline import GitHub
from test_safety import attempt,row

def test_publish_conflict_rebases_preserving_other_runner(monkeypatch):
 old=merge({},[attempt()])
 remote=merge(old,[attempt('B',route='mac')])
 snapshots=iter([('old-head',old),('new-head',remote)])
 blobs=[];updates=[]
 client=object.__new__(GitHub)
 monkeypatch.setattr(client,'read',lambda:next(snapshots))
 monkeypatch.setattr('pipeline.time.sleep',lambda _:None)
 def api(method,path,**kwargs):
  if path=='git/blobs':blobs.append(kwargs['json']['content']);return {'sha':str(len(blobs))}
  if path.startswith('git/commits/') and method=='GET':return {'tree':{'sha':'base-tree'}}
  if path=='git/trees':return {'sha':'tree'}
  if path=='git/commits':return {'sha':'commit'}
  if method=='PATCH':
   updates.append(kwargs['json'])
   if len(updates)==1:
    response=requests.Response();response.status_code=422
    raise requests.HTTPError('not a fast forward',response=response)
   return {}
  raise AssertionError((method,path))
 monkeypatch.setattr(client,'api',api)
 monkeypatch.setattr('pipeline.REGISTRY',{'A':{},'B':{}})
 result,sha=client.publish([attempt(stamp='2026-11-23T15:00:00+00:00',rows=[row(job='new')])],{'id':'test','route':'cloud','completed_at':'2026-11-23T15:00:00+00:00'})
 assert result['firms']['B']['rows']==remote['firms']['B']['rows']
 assert result['firms']['A']['rows'][0]['job_id']=='new'
 assert all(u['force'] is False for u in updates)
 published=list(csv.DictReader(io.StringIO(blobs[-3])))
 assert {(r['firm'],r['job_id']) for r in published}=={('A','new'),('B','1')}

def test_github_transport_recovers_a_dropped_connection(monkeypatch):
 from types import SimpleNamespace
 client=object.__new__(GitHub);calls=[]
 def request(*args,**kwargs):
  calls.append(args)
  if len(calls)==1:raise requests.ConnectionError('peer closed idle connection')
  response=requests.Response();response.status_code=200;response._content=b'{"object":{"sha":"live-head"}}';return response
 client.s=SimpleNamespace(request=request)
 monkeypatch.setattr('pipeline.time.sleep',lambda _:None)
 assert client.api('GET','git/ref/heads/feed')['object']['sha']=='live-head'
 assert len(calls)==2
