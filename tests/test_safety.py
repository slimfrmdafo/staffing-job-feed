import csv,io,copy
import pytest
from core import blank,csv_text,merge,keep,validate

def row(firm='A',job='1'):
 r=blank();r.update(firm=firm,job_id=job,title='Business Analyst',url='https://example.org/job/'+job,description='a, "quoted"\nfull description',city='Charlotte',state='NC');return r

def attempt(firm='A',stamp='2026-11-23T12:00:00+00:00',ok=True,rows=None,route='cloud'):
 return dict(firm=firm,started_at=stamp,completed_at=stamp,ok=ok,rows=[row(firm)] if rows is None else rows,route=route)

def test_failure_carries_forward_and_other_firm_survives():
 state=merge({},[attempt(),attempt('B',route='mac')]);old=copy.deepcopy(state)
 state=merge(state,[attempt(ok=False,stamp='2026-11-23T13:00:00+00:00')])
 assert state['firms']['A']['rows']==old['firms']['A']['rows']
 assert state['firms']['B']==old['firms']['B']

def test_older_pull_never_replaces_newer_success():
 state=merge({},[attempt(stamp='2026-11-23T13:00:00+00:00',rows=[row(job='new')],route='mac')])
 state=merge(state,[attempt()]);assert state['firms']['A']['rows'][0]['job_id']=='new'

def test_successful_empty_replaces_only_its_firm():
 state=merge({},[attempt(),attempt('B')]);state=merge(state,[attempt(stamp='2026-11-23T13:00:00+00:00',rows=[])])
 assert state['firms']['A']['rows']==[];assert len(state['firms']['B']['rows'])==1

def test_csv_round_trip_and_header():
 r=row();data=csv_text([r]);assert next(csv.reader(io.StringIO(data)))==list(r)
 assert list(csv.DictReader(io.StringIO(data)))==[r]

def test_duplicate_invalid_enum_and_https_rejected():
 with pytest.raises(ValueError):validate([row(),row()])
 r=row();r['job_type']='Full Time'
 with pytest.raises(ValueError):validate([r])
 r=row();r['url']='http://example.org'
 with pytest.raises(ValueError):validate([r])

def test_filter_uses_upper_pay_unknown_kept_and_sc_locations():
 r=row();assert keep(r)
 r.update(city='Fort Mill',state='SC',pay_min='25',pay_max='40',pay_unit='hour');assert keep(r)
 r['pay_max']='28';assert not keep(r)
 r.update(city='Toronto',state='',work_arrangement='remote');assert not keep(r)

def test_empty_failed_attempt_cannot_clear_rows():
 state=merge({},[attempt()]);state=merge(state,[attempt(ok=False,stamp='2026-11-23T14:00:00+00:00',rows=[])])
 assert len(state['firms']['A']['rows'])==1

def test_stale_mac_failure_does_not_replace_newer_cloud_status():
 state=merge({},[attempt(stamp='2026-11-23T14:00:00+00:00')]);state=merge(state,[attempt(stamp='2026-11-23T13:00:00+00:00',ok=False)])
 assert state['firms']['A']['attempts']['cloud']['ok']

def test_explicit_remote_us_and_coordinates_are_supported():
 r=row();r.update(city='',state='',work_arrangement='remote');assert keep(r,country='USA')
 r.update(work_arrangement='onsite');assert keep(r,nearby=True)
