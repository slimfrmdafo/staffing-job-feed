import json
from types import SimpleNamespace
import collectors

def response(html,url):return SimpleNamespace(text=html,url=url)

def test_live_schema_survives_hidden_closed_template(monkeypatch):
 url='https://example.org/job/123'
 schema={'@type':'JobPosting','title':'Business Analyst','description':'Full live description including stakeholder work and controls.','jobLocation':{'address':{'addressLocality':'Charlotte','addressRegion':'North Carolina'}}}
 html='<script type="application/ld+json">'+json.dumps(schema)+'</script><div hidden>This job is no longer available.</div>'
 monkeypatch.setattr(collectors,'get',lambda url:response(html,url))
 r=collectors.detail('TEKsystems',{'url':url,'job_id':'123'})
 assert r and r['title']=='Business Analyst' and r['state']=='NC'

def test_robert_half_keeps_requirements_and_corrects_malformed_region(monkeypatch):
 url='https://example.org/job/123'
 schema={'@type':'JobPosting','title':'Project Manager','description':'Summary only','jobLocation':{'address':{'addressLocality':'Charlotte','addressRegion':'03200'}}}
 html='<script type="application/ld+json">'+json.dumps(schema)+'</script><rhcl-job-card variant="listing"><div slot="description">Full responsibilities.</div><div slot="requirements">PMP certification required.</div><li data-subslot="location">Charlotte, NC</li></rhcl-job-card>'
 monkeypatch.setattr(collectors,'get',lambda url:response(html,url))
 r=collectors.detail('Robert Half',{'url':url,'job_id':'123'})
 assert r['state']=='NC' and 'Full responsibilities.' in r['description'] and 'PMP certification required.' in r['description']
 assert r['required_certifications']=='PMP certification required'

def test_partial_detail_failure_rejects_whole_firm(monkeypatch):
 def fake(firm,seed):
  if seed['url'].endswith('bad'):raise collectors.CollectionError('Security check')
  return None
 monkeypatch.setattr(collectors,'detail',fake)
 import pytest
 with pytest.raises(collectors.CollectionError,match='1/2 detail pages failed'):
  collectors.fetch_details('Mindlance',[{'url':'https://example.org/good'},{'url':'https://example.org/bad'}])

def test_dexian_visible_city_overrides_county_schema(monkeypatch):
 url='https://example.org/jobs/business-analyst-1023-456/'
 schema={'@type':'JobPosting','title':'Business Analyst','description':'Twelve-month contract position supporting banking operations.','jobLocation':{'address':{'addressLocality':'Mecklenburg','addressRegion':'NC'}}}
 html='<script type="application/ld+json">'+json.dumps(schema)+'</script><div class="meta-label">Location</div><div class="meta-content">Charlotte, NC</div>'
 monkeypatch.setattr(collectors,'get',lambda url:response(html,url))
 r=collectors.detail('Signature Consultants',{'url':url,'job_id':'1023'})
 assert r['city']=='Charlotte' and r['state']=='NC'

def test_maintenance_redirect_is_failure_not_closed(monkeypatch):
 import pytest
 monkeypatch.setattr(collectors,'get',lambda url:response('<h1>Please Check Back Soon</h1>','https://www.apexsystems.com/jobs-maintenance'))
 with pytest.raises(collectors.CollectionError,match='under maintenance'):
  collectors.detail('Apex Systems',{'url':'https://www.apexsystems.com/job/123_usa/project-manager','job_id':'123'})

def test_invalid_firm_rows_fail_only_that_firm(monkeypatch):
 from test_safety import row
 r=row('Robert Half');r['work_arrangement']='maybe'
 monkeypatch.setitem(collectors.ADAPTERS,'rh_search',lambda firm,config:([r],{}))
 result=collectors.collect('Robert Half','cloud')
 assert not result['ok'] and 'Invalid work_arrangement' in result['error']

def test_source_duplicate_ids_do_not_look_like_missing_pages(monkeypatch):
 job={'requisitionId':'native-123','jobTitle':'Business Analyst','workAddress':{'administrativeArea':'NC','locality':'Charlotte'},'jobType':'Contract','postedDate':'2026-11-23'}
 search={'jobs':[job,job],'pageMetadata':{'number':1,'totalElements':2,'totalPages':1}}
 def read(url,**kwargs):
  return SimpleNamespace(json=lambda: {'description':'Full details of the Charlotte banking business analyst contract role.'} if url.endswith('/details') else search)
 monkeypatch.setattr(collectors,'get',read)
 rows,info=collectors.insight('Insight Global',{})
 assert len(rows)==1 and info['enumerated']==1 and info['enumerated_raw']==2 and info['advertised']==2

def test_rendered_detail_reuses_full_contract_without_refetch(monkeypatch):
 url='https://example.org/portal/job/123'
 schema={'@type':'JobPosting','title':'Business Analyst','description':'Full rendered job responsibilities and qualifications.','jobLocation':{'address':{'addressLocality':'Charlotte','addressRegion':'NC'}}}
 html='<script type="application/ld+json">'+json.dumps(schema)+'</script>'
 def no_http(*args,**kwargs):raise AssertionError('Rendered detail must not refetch the JavaScript shell')
 monkeypatch.setattr(collectors,'get',no_http)
 r=collectors.detail('Mindlance',{'url':url,'job_id':'123'},html_text=html)
 assert r['description']=='Full rendered job responsibilities and qualifications.'
 assert r['state']=='NC'

def test_rendered_security_challenge_still_rejects_full_detail():
 import pytest
 with pytest.raises(collectors.CollectionError,match='Human security check'):
  collectors.detail('Mindlance',{'url':'https://example.org/job/123','job_id':'123'},html_text='<h1>Quick security check</h1><p>Please confirm you are human</p>')
