import json
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
 b=pw.chromium.launch(headless=True);p=b.new_page()
 for name,url in [('Duke Energy','https://dukeenergy.wd1.myworkdayjobs.com/search'),('Wells Fargo','https://wf.wd1.myworkdayjobs.com/WellsFargoJobs'),('Ally','https://ally.wd1.myworkdayjobs.com/Ally')]:
  try:
   r=p.goto(url,wait_until='networkidle',timeout=60000);print(json.dumps({'name':name,'status':r.status if r else None,'text':p.locator('body').inner_text()[:1500]}),flush=True)
  except Exception as e:print(json.dumps({'name':name,'error':str(e)[:250]}),flush=True)
 b.close()
