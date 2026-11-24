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
