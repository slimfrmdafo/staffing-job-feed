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
