import json
import pytest
from employer_collectors import parse_location,workday_row,keep_employer,match,REGISTRY,PRIORITY
from collectors import CollectionError
from employer_pipeline import EmployerGitHub
from pipeline import GitHub

def test_priority_employers_are_present_and_attemptable():
 assert len(PRIORITY)==8
 assert all(f in REGISTRY and REGISTRY[f]['adapter'] in ('workday','bofa','phenom') for f in PRIORITY)

def test_workday_addresses_accept_both_state_orders():
 assert parse_location('USA, NC, Charlotte, 620 S Tryon St')==('Charlotte','NC')
 assert parse_location('CHARLOTTE, NC')==('Charlotte','NC')
 assert parse_location('Fort Mill, South Carolina, United States')==('Fort Mill','SC')
 assert parse_location('Charlotte, MI')==('Charlotte','MI')

def posting(**fields):
 j={'jobReqId':'R-123','title':'Senior Business Analyst','jobDescription':'<p>Full description of the actual role.</p>','location':'New York, NY','additionalLocations':['Charlotte, NC'],'country':{'descriptor':'United States of America'},'canApply':True,'posted':True,'startDate':'2026-11-23'};j.update(fields);return {'jobPostingInfo':j}

def test_multilocation_uses_explicit_charlotte_address_and_full_detail():
 r,country=workday_row('Wells Fargo','https://example.com/Careers','/job/x',posting())
 assert (r['city'],r['state'])==('Charlotte','NC')
 assert r['description']=='Full description of the actual role.'
 assert r['job_id']=='R-123'
 assert keep_employer(r,country)

def test_closed_or_incomplete_detail_does_not_become_a_live_row():
 from collectors import ClosedListing
 with pytest.raises(ClosedListing):workday_row('A','https://example.com','/job/x',posting(canApply=False))
 with pytest.raises(CollectionError):workday_row('A','https://example.com','/job/x',posting(jobDescription=''))

def test_employer_roles_exclude_tellers_and_store_roles():
 assert match('Senior Business Execution Consultant')
 assert match('Strategy and Operations Manager')
 assert not match('Branch Operations Manager')
 assert not match('Retail Store Operations Manager')
 assert not match('Teller Operations Specialist')
 assert not match('Software Engineering Project Manager - Construction')

def test_feed_state_and_files_are_isolated():
 assert EmployerGitHub.state_file!=GitHub.state_file
 assert EmployerGitHub.csv_file=='employer_jobs.csv'
 assert EmployerGitHub.status_file=='employer_status.txt'

def test_hidden_former_job_retains_whole_employer_snapshot():
 from employer_pipeline import preserve_unreadable_existing
 a={'firm':'Wells Fargo','ok':True,'rows':[{'job_id':'new'}],'info':{'unpublished_index_ids':['R-123']}}
 prior={'firms':{'Wells Fargo':{'rows':[{'job_id':'R-123'}]}}}
 preserve_unreadable_existing(a,prior)
 assert a['ok'] is False and a['rows']==[]
 assert 'retaining complete prior' in a['error']

def test_id_only_nonpublic_entry_does_not_hide_prior_public_data():
 from employer_pipeline import preserve_unreadable_existing
 a={'firm':'Wells Fargo','ok':True,'rows':[],'info':{'unpublished_index_ids':['never-public']}}
 preserve_unreadable_existing(a,{'firms':{'Wells Fargo':{'rows':[{'job_id':'R-123'}]}}})
 assert a['ok'] is True

def test_employer_publication_updates_only_its_files_on_existing_tree(monkeypatch):
 from employer_pipeline import EmployerGitHub
 from core import merge
 from test_safety import attempt
 state=merge({},[attempt()]);client=object.__new__(EmployerGitHub);calls=[]
 monkeypatch.setattr(client,'read',lambda:('shared-head',state))
 def api(method,path,**kwargs):
  calls.append((method,path,kwargs.get('json')))
  if path.startswith('git/commits/') and method=='GET':return {'tree':{'sha':'shared-tree-containing-staffing'}}
  if path=='git/blobs':return {'sha':'blob'}
  if path=='git/trees':return {'sha':'new-tree'}
  if path=='git/commits':return {'sha':'new-commit'}
  if method=='PATCH':return {}
  raise AssertionError((method,path))
 monkeypatch.setattr(client,'api',api)
 client.publish([],{'route':'cloud','completed_at':'2026-11-23T15:00:00+00:00'})
 tree=next(payload for method,path,payload in calls if path=='git/trees')
 assert tree['base_tree']=='shared-tree-containing-staffing'
 assert {e['path'] for e in tree['tree']}=={'employer_jobs.csv','employer_status.txt','employer_state.json'}
 update=next(payload for method,path,payload in calls if method=='PATCH')
 assert update['force'] is False

def test_capped_workday_index_partitions_all_locations_and_keeps_older_jobs():
 from employer_collectors import workday_index
 class FakeBrowser:
  def api(self,url,body):
   selected=body['appliedFacets'].get('locations',[])
   if not selected:return {'total':2,'jobPostings':[{'externalPath':'/job/a','title':'A'},{'externalPath':'/job/b','title':'B'}],'facets':[{'facetParameter':'locations','values':[{'id':'local','count':2},{'id':'other','count':2}]}]}
   names=['a','b'] if selected==['local'] else ['c','d']
   return {'total':2,'jobPostings':[{'externalPath':'/job/'+n,'title':n} for n in names]}
 jobs,info=workday_index(FakeBrowser(),'https://example.com',{},cap=2)
 assert set(jobs)=={'/job/a','/job/b','/job/c','/job/d'}
 assert info['location_partitions']==2
 assert info['enumerated']==4

def test_later_workday_pages_can_omit_total_without_losing_completeness():
 from employer_collectors import workday_index
 class FakeBrowser:
  def api(self,url,body):
   return {'total':2 if body['offset']==0 else 0,'jobPostings':[{'externalPath':'/job/'+str(body['offset']),'title':'A'}]}
 jobs,info=workday_index(FakeBrowser(),'https://example.com',{})
 assert len(jobs)==2 and info['enumerated_raw']==2

def test_explicit_virtual_worker_is_remote_but_not_remote_office_is_onsite():
 r,country=workday_row('AT&T','https://example.com','/job/x',posting(location='Dallas, TX',additionalLocations=[],remoteType='Virtual Worker'))
 assert r['work_arrangement']=='remote' and keep_employer(r,country)
 r,country=workday_row('AT&T','https://example.com','/job/x',posting(location='Dallas, TX',additionalLocations=[],remoteType='Office Worker (NOT Remote)'))
 assert r['work_arrangement']=='onsite' and not keep_employer(r,country)

def test_portal_duplicate_pages_cannot_be_published_as_complete(monkeypatch):
 import requests
 from employer_collectors import phenom
 class Response:
  def raise_for_status(self):pass
  def json(self):return {'refineSearch':{'status':200,'totalHits':2,'data':{'jobs':[{'jobSeqNo':'same','jobId':'same','title':'Project Manager'}]}}}
 payloads=[]
 def post(url,**kwargs):payloads.append(kwargs['json']);return Response()
 monkeypatch.setattr(requests,'post',post)
 with pytest.raises(CollectionError,match='duplicate pagination'):
  phenom("Lowe's",{'root':'https://example.com'})
 assert payloads[0]['sort']=={'order':'asc','field':'dateCreated'}

def test_county_only_posting_does_not_invent_a_city():
 assert parse_location('Mecklenburg Mecklenburg County, NC')==('','NC')
 assert parse_location('Wake County, North Carolina')==('','NC')
 assert parse_location('Indian Land, SC')==('Indian Land','SC')
 assert parse_location('Wesley Chapel, NC')==('Wesley Chapel','NC')
