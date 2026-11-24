from cloud_clock import tick

def test_tick_queues_unattended_successor_before_collector():
 calls=[]
 def call(method,path,payload=None):
  calls.append((method,path,payload));return {'state':'active'}
 tick(call,run_id='timer-123')
 assert calls[1]==('POST','actions/workflows/clock.yml/dispatches',{'ref':'main','inputs':{'start_now':'false'}})
 assert calls[2][1]=='actions/workflows/collect.yml/dispatches'
 assert calls[2][2]['inputs']['timer_run_id']=='timer-123'

def test_disabled_clock_cannot_renew_or_launch_jobs():
 calls=[]
 def call(method,path,payload=None):calls.append(method);return {'state':'disabled_manually'}
 tick(call,run_id='timer-123');assert calls==['GET']
