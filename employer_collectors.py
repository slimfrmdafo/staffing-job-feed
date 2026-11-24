"""Complete first-party employer searches with ordinary browser rendering."""
import concurrent.futures,json,os,pathlib,re,time,traceback
from urllib.parse import urlparse,urljoin,unquote
from bs4 import BeautifulSoup
from core import blank,enrich,keep,now,plain,state_code,STATES,LOCAL,title_match,validate,job_type,number
from collectors import CollectionError,ClosedListing,walk_json,schema_row,get,assigned_json

# URLs are employers' public applicant systems, linked by their own career sites.
PRIORITY=['Bank of America','Wells Fargo','Truist','Duke Energy',"Lowe's",'Ally Financial','TIAA','Citigroup']
WORKDAY={
 'Bank of America':'https://ghr.wd1.myworkdayjobs.com/Lateral-US',
 'Wells Fargo':'https://wf.wd1.myworkdayjobs.com/WellsFargoJobs',
 'Truist':'https://truist.wd1.myworkdayjobs.com/Careers',
 'Duke Energy':'https://dukeenergy.wd1.myworkdayjobs.com/search',
 "Lowe's":'https://lowes.wd5.myworkdayjobs.com/LWS_External_CS',
 'Ally Financial':'https://ally.wd1.myworkdayjobs.com/Ally',
 'TIAA':'https://tiaa.wd1.myworkdayjobs.com/Search',
 'Citigroup':'https://citi.wd5.myworkdayjobs.com/2',
 'AT&T':'https://att.wd1.myworkdayjobs.com/ATTGeneral',
 'Trane Technologies':'https://tranetechnologies.wd12.myworkdayjobs.com/Trane_Technologies_Careers',
 'The Hartford':'https://thehartford.wd5.myworkdayjobs.com/Careers_External',
 'Albemarle':'https://albemarle.wd5.myworkdayjobs.com/External',
 'Sunbelt Rentals':'https://sunbeltrentals.wd1.myworkdayjobs.com/sbcareers',
 'Premier':'https://premierinc.wd1.myworkdayjobs.com/External_Professional',
 'RXO':'https://rxo.wd501.myworkdayjobs.com/rxojobs',
 'Carrier Global':'https://carrier.wd5.myworkdayjobs.com/jobs',
 'Hendrick Automotive Group':'https://hendrick.wd5.myworkdayjobs.com/HendrickCareers',
 'American Tire Distributors':'https://atd.wd1.myworkdayjobs.com/American_Tire_Distributors',
 'Movement Mortgage':'https://movement.wd1.myworkdayjobs.com/Careers',
 "Kohl's":'https://kohls.wd1.myworkdayjobs.com/KohlsCareers',
 'OrthoCarolina':'https://ths.wd504.myworkdayjobs.com/OrthoCarolina',
 'Campbell Snacks':'https://campbellsoup.wd5.myworkdayjobs.com/ExternalCareers_GlobalSite',
 'J.B. Hunt':'https://jbhunt.wd501.myworkdayjobs.com/Careers',
 "Dick's Sporting Goods":'https://dickssportinggoods.wd1.myworkdayjobs.com/DSG',
 'Prysmian Group':'https://prysmiangroup.wd3.myworkdayjobs.com/Careers',
 'Ryder System':'https://ryder.wd5.myworkdayjobs.com/RyderCareers',
 'Curtiss-Wright':'https://curtisswright.wd1.myworkdayjobs.com/CW_External_Career_Site',
 'Rosendin Electric':'https://rosendin.wd1.myworkdayjobs.com/Careers',
 'Celgard':'https://akamerica.wd501.myworkdayjobs.com/aka/?hiringCompany=2f24a4199827013877171f1c223b682f',
 'UFP Industries':'https://ufpi.wd503.myworkdayjobs.com/ufpi',
 'Husqvarna Group':'https://husqvarna.wd3.myworkdayjobs.com/External',
 'CLA':'https://cliftonlarsonallen.wd1.myworkdayjobs.com/CLA',
 'Whistle Express Car Wash':'https://whistleexpresscarwash.wd108.myworkdayjobs.com/Whistle_Express_Car_Wash',
}
REGISTRY={f:{'adapter':'workday','url':u} for f,u in WORKDAY.items()}
WORKDAY.update({'Comporium':'https://comporium.wd1.myworkdayjobs.com/Comporium_Careers','Pepsi Bottling Ventures':'https://pbv.wd503.myworkdayjobs.com/external','North Carolina State Government':'https://nc.wd108.myworkdayjobs.com/NC_Careers','Charlotte Douglas International Airport':'https://charlottenc.wd12.myworkdayjobs.com/citgov','City of Charlotte':'https://charlottenc.wd12.myworkdayjobs.com/citgov'})
REGISTRY.update({f:{'adapter':'workday','url':u} for f,u in WORKDAY.items()})
REGISTRY['Charlotte Douglas International Airport']['require_text']=r'\b(?:airport|aviation)\b'
REGISTRY['City of Charlotte']['exclude_text']=r'\b(?:airport|aviation)\b'
REGISTRY.update({
 'Honeywell':{'adapter':'oracle','url':'https://careers.honeywell.com/en/sites/Honeywell'},
})
EXCLUDE=re.compile(r'\b(?:teller|branch (?:banker|manager|leader|operations)|personal banker|relationship banker|software engineering|retail (?:store|sales)|store (?:manager|leader|operations)|cashier|merchandis|fulfillment|forklift|driver|hvac|electrician|construction|field service|installer|mechanic|technician|car wash|intern(?:ship)?)\b',re.I)
STRATEGY=re.compile(r'strategy\s*(?:and|&|/)\s*operations|strategic (?:execution|initiatives)|process (?:analyst|consultant)|business (?:execution|management|strategy)|operational (?:excellence|effectiveness)',re.I)
def match(title):return not EXCLUDE.search(title) and (title_match(title) or bool(STRATEGY.search(title)))

def parse_location(text):
    text=plain(text).strip();lower=text.lower()
    for city in sorted(LOCAL,key=len,reverse=True):
        if re.search(r'\b'+re.escape(city)+r'\b',lower):
            # Never mistake Charlotte in another state or a city name in a street address.
            m=re.search(r'\b(NC|SC|North Carolina|South Carolina)\b',text,re.I)
            if m:return city.title(),state_code(m[1].upper() if len(m[1])==2 else m[1].title())
    for name,code in sorted(STATES.items(),key=lambda x:len(x[0]),reverse=True):
        m=re.search(r'\b'+re.escape(name)+r'\b',text,re.I)
        if m:return re.sub(r'[,\s-]+$','',text[:m.start()]).strip(),code
    m=re.search(r'^(.*?)[,\s-]+([A-Z]{2})(?:\b|\s*\d)',text)
    if m and m[2] in STATES.values():return m[1].strip(),m[2]
    return '', ''

def workday_row(firm,base,path,data):
    j=data.get('jobPostingInfo') or {}
    if not j.get('jobReqId') or not j.get('title') or not j.get('jobDescription'):raise CollectionError('Full Workday posting fields missing: '+path)
    if j.get('canApply') is False or j.get('posted') is False:raise ClosedListing('No longer accepting applications')
    r=blank();r.update(firm=firm,job_id=str(j['jobReqId']),title=plain(j['title']),description=plain(j['jobDescription']),url=base.rstrip('/')+path)
    locations=[j.get('location') or '']+list(j.get('additionalLocations') or [])
    locations=[x.get('descriptor','') if isinstance(x,dict) else str(x) for x in locations]
    parsed=[parse_location(x) for x in locations];local=next((x for x in parsed if x[0].lower() in LOCAL and x[1] in ('NC','SC')),None)
    city,state=local or next((x for x in parsed if x[1]),('',''));r.update(city=city,state=state)
    remote=str(j.get('remoteType') or j.get('workplaceType') or '')
    if re.fullmatch(r'(?:fully )?remote',remote,re.I):r['work_arrangement']='remote'
    elif remote.lower()=='hybrid':r['work_arrangement']='hybrid'
    elif remote.lower() in ('onsite','on-site'):r['work_arrangement']='onsite'
    if any(re.search(r'\bremote\b',x,re.I) for x in locations) and not re.search(r'hybrid|partially remote',remote,re.I):r['work_arrangement']='remote'
    typ=' '.join(str(j.get(k) or '') for k in ('workerSubType','jobType','employmentType'))
    r['job_type']=job_type(typ)
    if not r['job_type'] and re.search(r'\bRegular\b',typ,re.I):r['job_type']='permanent'
    date=str(j.get('startDate') or '')
    if re.match(r'^\d{4}-\d{2}-\d{2}',date):r['posted_date']=date[:10]
    enrich(r,remote+'\n'+r['description'])
    country=j.get('country') or {};country=country.get('descriptor','') if isinstance(country,dict) else str(country)
    country='US' if country in ('United States of America','United States','USA','US') else country
    # Explicit "remote" statements in prose can be qualified by mandatory office attendance.
    if r['work_arrangement']=='remote' and re.search(r'(?:not (?:a )?remote|not (?:eligible|available) for remote|no remote (?:work|option)|hybrid.{0,70}(?:in.office|onsite)|(?:in.office|onsite).{0,40}(?:[2-5]|two|three|four|five) days)',r['description'],re.I):r['work_arrangement']='hybrid' if re.search('hybrid',r['description'],re.I) else ''
    return r,country

class Browser:
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.pw=sync_playwright().start()
        try:self.browser=self.pw.chromium.launch(headless=True);self.page=self.browser.new_page();return self
        except Exception:self.pw.stop();raise
    def __exit__(self,*args):self.browser.close();self.pw.stop()
    def open(self,url):
        response=self.page.goto(url,wait_until='networkidle',timeout=60000)
        if response and response.status>=400:raise CollectionError(f'Browser HTTP {response.status}: {url}')
        text=self.page.locator('body').inner_text()
        if re.search(r'quick security check|verify you are human|access denied|confirm you.re human',text,re.I):raise CollectionError('Human security check: '+url)
        return self.page.content()
    def api(self,url,body=None):
        for attempt in range(3):
            d=self.page.evaluate('''async ({url,body})=>{const r=await fetch(url,body===null?{signal:AbortSignal.timeout(45000)}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(45000)});return {status:r.status,text:await r.text()}}''',{'url':url,'body':body})
            if d['status'] in (404,410):raise ClosedListing('HTTP '+str(d['status'])+': '+url)
            if d['status']==200:
                try:return json.loads(d['text'])
                except ValueError:raise CollectionError('Non-JSON public job response: '+url)
            if d['status'] in (429,500,502,503,504) and attempt<2:time.sleep(2+attempt);continue
            raise CollectionError(f"Browser search HTTP {d['status']}: {url}")

def workday(firm,config):
    from urllib.parse import parse_qs
    with Browser() as b:
        html=b.open(config['url']);tenant=re.search(r'\btenant:\s*"([^"]+)"',html);site=re.search(r'\bsiteId:\s*"([^"]+)"',html)
        if not tenant or not site:raise CollectionError('Workday site configuration missing')
        root='https://'+urlparse(b.page.url).netloc;base=root+'/'+site[1];api=root+'/wday/cxs/'+tenant[1]+'/'+site[1]
        facets={};query=parse_qs(urlparse(config['url']).query)
        if 'hiringCompany' in query:facets['hiringCompany']=query['hiringCompany']
        def search(offset):return b.api(api+'/jobs',{'appliedFacets':facets,'limit':20,'offset':offset,'searchText':''})
        first=search(0)
        # Restrict only by an explicit US country facet supplied by this exact site.
        for obj in walk_json(first.get('facets',[])):
            if re.search(r'country',str(obj.get('descriptor','')),re.I) and obj.get('facetParameter'):
                us=[v['id'] for v in obj.get('values',[]) if v.get('descriptor') in ('United States of America','United States','USA')]
                if us:facets[obj['facetParameter']]=us;first=search(0);break
        if not isinstance(first.get('total'),int) or not isinstance(first.get('jobPostings'),list):raise CollectionError('Workday total/list missing')
        total=first['total'];seen={};raw=0;offset=0;unpublished=[]
        while True:
            d=first if offset==0 else search(offset);jobs=d.get('jobPostings');count=d.get('total')
            if not isinstance(jobs,list) or not isinstance(count,int):raise CollectionError('Workday pagination data missing')
            if count not in (0,total):raise CollectionError(f'Workday search changed during pagination ({total} to {count}); retain prior snapshot')
            fresh=0
            for j in jobs:
                key=j.get('externalPath')
                if not key:
                    if set(j)=={'bulletFields'} and len(j['bulletFields'])==1 and re.fullmatch(r'[A-Za-z0-9-]+',str(j['bulletFields'][0])):
                        native=str(j['bulletFields'][0]);unpublished.append(native);key='@unpublished:'+native
                    else:raise CollectionError('Workday search ID/path missing: '+repr(j)[:700])
                if key not in seen:fresh+=1
                seen[key]=j
            raw+=len(jobs)
            if raw>=total:break
            if not jobs or not fresh:raise CollectionError('Workday pagination empty/repeated before advertised total')
            offset+=len(jobs)
            if offset>60000:raise CollectionError('Workday pagination safety limit')
        if raw!=total:raise CollectionError(f'Workday advertised {total}, read {raw}')
        rows=[];details=0;closed=0
        for path,j in seen.items():
            if not match(j.get('title','')):continue
            try:
                d=b.api(api+path);r,country=workday_row(firm,base,path,d);details+=1
            except ClosedListing:closed+=1;continue
            if not match(r['title']):continue
            text=r['title']+'\n'+r['description']
            if config.get('require_text') and not re.search(config['require_text'],text,re.I):continue
            if config.get('exclude_text') and re.search(config['exclude_text'],text,re.I):continue
            if keep_employer(r,country):rows.append(r)
        return rows,{'enumerated':len(seen),'enumerated_raw':raw,'advertised':total,'details_read':details,'closed_during_pull':closed,'kept':len(rows),'method':'ordinary browser + first-party full posting endpoint','scope_facets':facets,'unpublished_index_ids':unpublished}

def keep_employer(r,country=''):
    if not match(r['title']):return False
    # core.keep uses the shared staffing role list; strategy roles extend it here.
    if title_match(r['title']):return keep(r,country=country)
    clone=dict(r);clone['title']='Business Operations Analyst';return keep(clone,country=country)

def collect(firm,route):
    start=now();config=REGISTRY[firm]
    try:
        adapter=ADAPTERS.get(config['adapter'])
        if not adapter:raise CollectionError('First-party '+config['adapter']+' job search needs adapter: '+config['url'])
        for retry in range(3):
            try:rows,info=adapter(firm,config);break
            except CollectionError as e:
                if 'changed during pagination' not in str(e) or retry==2:raise
                time.sleep(2)
        validate(rows)
        result={'firm':firm,'route':route,'started_at':start,'completed_at':now(),'ok':True,'rows':rows,'info':info}
        print(f'{firm}: OK {len(rows)} listings; {info}',flush=True);return result
    except Exception as e:
        error=(type(e).__name__+': '+str(e))[:1800];print(f'{firm}: FAILED {error}',flush=True)
        return {'firm':firm,'route':route,'started_at':start,'completed_at':now(),'ok':False,'rows':[],'error':error}
ADAPTERS={'workday':workday}

def bofa(firm,config):
    endpoint='https://careers.bankofamerica.com/services/jobssearchservlet';seen={};total=None;raw=0
    for offset in range(0,40000,100):
        d=get(endpoint,params={'start':offset,'rows':offset+100,'search':'getAllJobs'}).json();jobs=d.get('jobsList');count=d.get('totalMatches')
        try:count=int(count)
        except (ValueError,TypeError):raise CollectionError('Bank of America search total missing')
        if total is None:total=count
        if count!=total:raise CollectionError('Bank of America search changed during pagination')
        if not isinstance(jobs,list):raise CollectionError('Bank of America search jobs missing')
        fresh=0
        for j in jobs:
            path=j.get('jcrURL')
            if not path:raise CollectionError('Bank of America canonical job link missing')
            if path not in seen:fresh+=1
            seen[path]=j
        raw+=len(jobs)
        if raw>=total:break
        if not jobs or not fresh:raise CollectionError('Bank of America search truncated/repeated')
    else:raise CollectionError('Bank of America pagination limit')
    if raw!=total:raise CollectionError('Bank of America advertised count mismatch')
    rows=[];details=0
    for path,j in seen.items():
        if not match(j.get('postingTitle','')):continue
        url='https://careers.bankofamerica.com'+path
        try:
            soup=BeautifulSoup(get(url).text,'html.parser');r=schema_row(firm,url,soup,{'job_id':path.split('/')[3]})
        except ClosedListing:continue
        if r is None or not r['description']:raise CollectionError('Bank of America full detail schema missing: '+url)
        details+=1
        if keep_employer(r,country='US'):rows.append(r)
    return rows,{'enumerated':len(seen),'enumerated_raw':raw,'advertised':total,'details_read':details,'kept':len(rows),'method':'employer search service + canonical full detail pages'}
REGISTRY['Bank of America']={'adapter':'bofa','url':'https://careers.bankofamerica.com/en-us/job-search'}
ADAPTERS['bofa']=bofa

def oracle(firm,config):
    base='https://ibqbjb.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/';seen={};total=None;raw=0
    for offset in range(0,40000,100):
        d=get(base+'recruitingCEJobRequisitions',params={'onlyData':'true','expand':'requisitionList','finder':f'findReqs;siteNumber=CX_1,facetsList=LOCATIONS;WORK_LOCATIONS;TITLES;CATEGORIES,limit=100,offset={offset}'}).json()
        items=d.get('items',[])
        if len(items)!=1:raise CollectionError('Oracle search payload missing')
        data=items[0];jobs=data.get('requisitionList');count=data.get('TotalJobsCount')
        if not isinstance(jobs,list) or not isinstance(count,int):raise CollectionError('Oracle search total/list missing')
        if total is None:total=count
        if count!=total:raise CollectionError('Oracle search changed during pagination')
        fresh=0
        for j in jobs:
            if not j.get('Id'):raise CollectionError('Oracle native requisition ID missing')
            if j['Id'] not in seen:fresh+=1
            seen[j['Id']]=j
        raw+=len(jobs)
        if raw>=total:break
        if not jobs or not fresh:raise CollectionError('Oracle search truncated/repeated')
    else:raise CollectionError('Oracle pagination limit')
    if raw!=total:raise CollectionError('Oracle advertised count mismatch')
    rows=[];details=0
    for job in seen.values():
        if not match(job.get('Title','')):continue
        response=get(base+'recruitingCEJobRequisitionDetails',params={'onlyData':'true','expand':'all','finder':'ById;Id='+job['Id']}).json();items=response.get('items',[])
        if not items:continue
        if len(items)!=1:raise CollectionError('Oracle detail ambiguous')
        j=items[0];details+=1
        if str(j.get('Id'))!=str(job['Id']) or not any(j.get(k) for k in ('ExternalDescriptionStr','ExternalResponsibilitiesStr','ExternalQualificationsStr')):raise CollectionError('Oracle full detail missing/mismatched: '+str(job['Id']))
        r=blank();r.update(firm=firm,job_id=str(j['Id']),title=plain(j.get('Title')),url='https://careers.honeywell.com/en/sites/Honeywell/job/'+str(j['Id']),description='\n\n'.join(plain(j.get(k)) for k in ('ExternalDescriptionStr','ExternalResponsibilitiesStr','ExternalQualificationsStr','OrganizationDescriptionStr','CorporateDescriptionStr') if j.get(k)))
        locs=[str(j.get('PrimaryLocation') or '')]+[str(x.get('Name') or x.get('LocationName') or '') for x in j.get('secondaryLocations',[]) if isinstance(x,dict)]
        parsed=[parse_location(x) for x in locs];r['city'],r['state']=next((x for x in parsed if x[0].lower() in LOCAL and x[1] in ('NC','SC')),next((x for x in parsed if x[1]),('','')))
        work=str(j.get('WorkplaceType') or '')
        if work.lower() in ('remote','hybrid','onsite'):r['work_arrangement']=work.lower()
        r['job_type']=job_type(str(j.get('JobType') or '')+' '+str(j.get('ContractType') or ''))
        if not r['job_type'] and str(j.get('ContractType') or '').lower()=='regular':r['job_type']='permanent'
        date=str(j.get('ExternalPostedStartDate') or '')
        if re.match(r'^\d{4}-\d{2}-\d{2}',date):r['posted_date']=date[:10]
        r['recruiter_name']=plain(j.get('ExternalContactName'));r['recruiter_email']=plain(j.get('ExternalContactEmail'))
        enrich(r,work+'\n'+r['description'])
        country=str(j.get('PrimaryLocationCountry') or '')
        if keep_employer(r,country=country):rows.append(r)
    return rows,{'enumerated':len(seen),'enumerated_raw':raw,'advertised':total,'details_read':details,'kept':len(rows),'method':'employer Oracle search + full requisition detail resource'}
ADAPTERS['oracle']=oracle
