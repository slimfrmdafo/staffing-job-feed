#!/usr/bin/env python3
"""Native hourly employer fallback; independent of the Codex application."""
import fcntl,os,pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parent
WORK=pathlib.Path(os.environ.get('STAFFING_WORK_DIR',str(ROOT.parent.parent/'work')))
WORK.mkdir(parents=True,exist_ok=True)
lock=(WORK/'employer-mac-run.lock').open('w')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:print('Employer Mac collection already running; skipped overlap',flush=True);sys.exit(0)
os.chdir(ROOT)
os.environ.update(GIT_TERMINAL_PROMPT='0',GH_PROMPT_DISABLED='1',EMPLOYER_TRIGGER='mac_launchd',PLAYWRIGHT_BROWSERS_PATH=str(WORK/'browsers'))
os.environ['PATH']='/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:'+os.environ.get('PATH','')
print('Starting native Mac employer fallback',flush=True)
subprocess.run(['git','pull','--ff-only'],check=True,timeout=120)
result=subprocess.run([sys.executable,str(ROOT/'employer_pipeline.py'),'--route','mac','--publish','--output',str(WORK/'employer-mac-last-run.json')],timeout=3000)
sys.exit(result.returncode)
