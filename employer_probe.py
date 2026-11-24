"""Diagnostic of public employer search endpoints from the cloud runner."""
import concurrent.futures,json,requests
SITES={'bofa':('ghr.wd1','ghr','lateral-us'),'wells':('wellsfargo.wd1','wellsfargo','WellsFargoJobs'),'truist':('truist.wd1','truist','Careers'),'duke':('dukeenergy.wd1','dukeenergy','search'),'lowes':('lowes.wd5','lowes','LWS_External_CS'),'ally':('ally.wd1','ally','Ally'),'tiaa':('tiaa.wd1','tiaa','Search'),'citi':('citi.wd5','citi','2')}
def one(item):
 name,(host,tenant,site)=item;root=f'https://{host}.myworkdayjobs.com';url=f'{root}/wday/cxs/{tenant}/{site}/jobs'
 try:
  session=requests.Session();r=session.post(url,json={'appliedFacets':{},'limit':20,'offset':0,'searchText':''},headers={'Accept':'application/json','Referer':f'{root}/{site}'},timeout=40)
  result={'name':name,'status':r.status_code,'body':r.text[:500]};print(json.dumps(result),flush=True);return result
 except Exception as e:return {'name':name,'error':str(e)}
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:results=list(ex.map(one,SITES.items()))
 open('employer-probe-result.json','w').write(json.dumps(results,indent=2))
