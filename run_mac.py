#!/usr/bin/env python3
"""Noninteractive Mac fallback runner; run by the hourly local automation."""
import fcntl,os,pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parent
WORK=ROOT.parent.parent/'work'
lock=(WORK/'mac-run.lock').open('w')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:
    print('Mac collection already running; skipped overlap');sys.exit(0)
os.chdir(ROOT)
os.environ['STAFFING_ROUTE']='mac'
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(WORK/'browsers')
os.environ['PATH']='/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:'+os.environ.get('PATH','')
subprocess.run(['git','pull','--ff-only'],check=True)
result=subprocess.run([sys.executable,str(ROOT/'pipeline.py'),'--route','mac','--publish','--output',str(WORK/'mac-last-run.json')])
sys.exit(result.returncode)
