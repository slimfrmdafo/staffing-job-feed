"""First-party site collectors. Incomplete enumeration/details fail the whole firm."""
import concurrent.futures, html, json, re, time, threading
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin, unquote, parse_qs
import requests
from bs4 import BeautifulSoup
from core import blank, plain, state_code, job_type, enrich, keep, title_match, now

class CollectionError(RuntimeError):pass
class ClosedListing(Exception):pass
LOCAL=threading.local()
def get(url, **kwargs):
    if not hasattr(LOCAL,'session'):
        LOCAL.session=requests.Session();LOCAL.session.headers['User-Agent']='Mozilla/5.0 (compatible; StaffingFeed/1.0; personal job discovery)'
    last=None
    for attempt in range(3):
        try:
            r=LOCAL.session.get(url,timeout=(15,60),**kwargs)
            if r.status_code in (404,410):raise ClosedListing(f'HTTP {r.status_code}: {url}')
            r.raise_for_status()
            if any(x in r.text[:15000].lower() for x in ['just a moment...','verify you are human','access denied']):raise CollectionError('Site challenge: '+url)
            return r
        except ClosedListing:raise
        except requests.RequestException as e:last=e;time.sleep(1+attempt)
    raise CollectionError(str(last))

def assigned_json(text, marker):
    if marker not in text:raise CollectionError('Expected search data missing: '+marker)
    return json.JSONDecoder(strict=False).raw_decode(text.split(marker,1)[1].lstrip())[0]

def walk_json(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():yield from walk_json(child)
    elif isinstance(value,list):
        for child in value:yield from walk_json(child)

def schemas(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:d=json.loads(script.string or script.get_text(),strict=False)
        except (ValueError,TypeError):continue
        yield from walk_json(d)

def schema_row(firm,url,soup,seed):
    js=next((x for x in schemas(soup) if x.get('@type')=='JobPosting'),None)
    if not js:return None
    valid=str(js.get('validThrough') or '')
    if valid and valid[:10]<now()[:10]:raise ClosedListing('Expired validThrough')
    r=blank();r.update(firm=firm,url=url,title=plain(js.get('title')),description=plain(js.get('description')))
    r['job_id']=seed.get('job_id','')
    identifier=js.get('identifier',{})
    if not r['job_id']:
        v=identifier.get('value') if isinstance(identifier,dict) else identifier
        if v and not str(v).startswith('http'):r['job_id']=str(v)
    if not r['job_id']:raise CollectionError('Poster job ID missing: '+url)
    locs=js.get('jobLocation',[]);locs=locs if isinstance(locs,list) else [locs]
    for loc in locs:
        if not isinstance(loc,dict):continue
        addr=loc.get('address',{})
        if isinstance(addr,dict):
            r['city']=plain(addr.get('addressLocality'));r['state']=state_code(addr.get('addressRegion'))
            if r['city'].lower() in __import__('core').LOCAL:break
    if js.get('jobLocationType')=='TELECOMMUTE':r['work_arrangement']='remote'
    typ=js.get('employmentType','');r['job_type']=job_type(' '.join(typ) if isinstance(typ,list) else typ)
    salary=js.get('baseSalary') or {};salary=salary[0] if isinstance(salary,list) and salary else salary
    if isinstance(salary,dict):
        val=salary.get('value') or {}
        if isinstance(val,dict):
            unit=str(val.get('unitText','')).lower();unit={'hour':'hour','hourly':'hour','year':'year','yearly':'year','annual':'year'}.get(unit,'')
            if unit:
                from core import number
                r.update(pay_min=number(val.get('minValue',val.get('value'))),pay_max=number(val.get('maxValue',val.get('value'))),pay_unit=unit)
    date=str(js.get('datePosted') or '')
    if re.match(r'^\d{4}-\d{2}-\d{2}',date):r['posted_date']=date[:10]
    exp=js.get('experienceRequirements')
    if isinstance(exp,str):r['required_experience']=plain(exp)
    cert=js.get('qualifications')
    if isinstance(cert,str) and cert:r['required_certifications']='' # prose isn't necessarily a certification
    # Seed is explicit search metadata; never replaces detail fields except identity.
    for k,v in seed.items():
        if k in r and v and not r[k]:r[k]=str(v)
    context=soup.get_text('\n',strip=True)
    return enrich(r,context)

def detail(firm,seed):
    url=seed['url']
    try:
        response=get(url)
        if 'ref=invalid_job' in response.url or any(x in response.url for x in ['jobs-maintenance']):raise ClosedListing('Listing no longer available')
        soup=BeautifulSoup(response.text,'html.parser')
        if re.search(r'(?:job (?:is no longer|has been filled)|position has been filled|job you are looking for is no longer)',soup.get_text(' ',strip=True),re.I):raise ClosedListing('Closed notice')
        row=schema_row(firm,url,soup,seed)
        if row is None and firm=='Beacon Hill':row=beacon_row(firm,url,soup,seed)
        if row is None:raise CollectionError('Full JobPosting data missing: '+url)
        if not row['title'] or len(row['description'])<100:raise CollectionError('Incomplete detail: '+url)
        return row if keep(row) else None
    except ClosedListing:return None

def fetch_details(firm,seeds):
    unique={x['url']:x for x in seeds};out=[];errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(detail,firm,s):s for s in unique.values()}
        for f in concurrent.futures.as_completed(futures):
            try:
                row=f.result()
                if row:out.append(row)
            except Exception as e:errors.append(str(e))
    if errors:raise CollectionError(f'{len(errors)}/{len(unique)} detail pages failed: '+'; '.join(errors[:3]))
    ids={}
    for r in out:ids[r['job_id']]=r
    return list(ids.values()),{'candidates':len(unique),'details_read':len(unique),'kept':len(ids)}

def sitemap_urls(url,job_pattern,visited=None):
    visited=set() if visited is None else visited
    if url in visited:raise CollectionError('Sitemap cycle')
    visited.add(url)
    try:root=ET.fromstring(get(url).content)
    except (ET.ParseError,ClosedListing) as e:raise CollectionError('Sitemap unavailable: '+url) from e
    ns='{http://www.sitemaps.org/schemas/sitemap/0.9}'
    if root.tag==ns+'sitemapindex':
        out=[]
        for child in root.findall(ns+'sitemap/'+ns+'loc'):out+=sitemap_urls(child.text,job_pattern,visited)
        return out
    if root.tag!=ns+'urlset':raise CollectionError('Unexpected sitemap format')
    urls=[x.text for x in root.findall(ns+'url/'+ns+'loc') if x.text and re.search(job_pattern,x.text)]
    if not urls:raise CollectionError('Job sitemap unexpectedly empty')
    return urls

def sitemap_collect(firm,config):
    urls=sitemap_urls(config['sitemap'],config['pattern']);seeds=[]
    for url in urls:
        slug=unquote(urlparse(url).path).replace('-',' ')
        if not title_match(slug):continue
        job_id=id_from_url(firm,url)
        seeds.append({'url':url,'job_id':job_id})
    rows,info=fetch_details(firm,seeds);info['enumerated']=len(urls);return rows,info

def id_from_url(firm,url):
    path=urlparse(url).path.rstrip('/');parts=path.split('/')
    if firm=='Robert Half':return parts[-1]
    if firm in ('TEKsystems','Aerotek'):return parts[-2]
    if firm=='Randstad':return parts[-2]
    if firm=='Brooksource':return parts[-1].split('-')[0]
    if firm=='Beacon Hill':return parts[-1].split('_')[0]
    if firm=='Vaco':return parts[2]
    if firm=='The Select Group':
        m=re.search(r'/(\d+)',path);return m[1] if m else ''
    return ''

def beacon_row(firm,url,soup,seed):
    body=soup.select_one('.job_description, .job-description, .job_description-content')
    if body is None:return None
    r=blank();r.update(firm=firm,url=url,job_id=seed['job_id'],description=body.get_text('\n',strip=True))
    h=soup.select_one('h1');r['title']=h.get_text(' ',strip=True) if h else ''
    text=soup.get_text('\n',strip=True)
    m=re.search(r'Location\s*\n([^\n]+)',text,re.I)
    if m:
        loc=m[1].strip().split(',');r['city']=loc[0].strip();r['state']=state_code(loc[-1].strip()) if len(loc)>1 else ''
    return enrich(r,text)

def jobdiva(firm,config):
    # Endpoint is embedded by the firm's own search site; the portal belongs to that firm.
    url='https://www2.jobdiva.com/candidates/myjobs/getportaljobs.jsp'
    response=get(url,params={'a':config['account'],'noofjobs':10000})
    try:root=ET.fromstring(response.content)
    except ET.ParseError as e:raise CollectionError('JobDiva XML invalid') from e
    jobs=root.findall('.//job')
    if not jobs or len(jobs)>=10000:raise CollectionError('JobDiva index empty or truncated')
    seeds=[]
    for j in jobs:
        title=j.findtext('title') or ''
        if not title_match(title):continue
        seeds.append({'url':j.findtext('portal_url'),'job_id':j.findtext('jobdiva_no') or j.findtext('jobdivaid')})
    rows,info=fetch_details(firm,seeds);info['enumerated']=len(jobs);return rows,info

def vaco(firm,config):
    seeds=[];seen=set();url='https://jobs.vaco.com/home';enumerated=0
    for page in range(1,301):
        soup=BeautifulSoup(get(url).text,'html.parser');links=soup.select('a[href]');current={}
        for a in links:
            href=urljoin(url,a['href']).split('#')[0]
            if re.search(r'https://jobs\.vaco\.com/job/\d+/',href):current[href]=a.get_text(' ',strip=True)
        if not current:raise CollectionError('Vaco search unexpectedly empty')
        fresh=set(current)-seen
        if not fresh:raise CollectionError('Vaco pagination repeated')
        seen.update(current);enumerated+=len(current)
        for href,title in current.items():
            if title_match(title):seeds.append({'url':href,'job_id':id_from_url(firm,href)})
        nxt=soup.find('a',attrs={'rel':'next'})
        if not nxt:nxt=next((a for a in links if a.get_text(' ',strip=True).lower() in ('next','next »','next page')),None)
        if not nxt:break
        url=urljoin(url,nxt['href'])
    else:raise CollectionError('Vaco exceeded safety page limit')
    rows,info=fetch_details(firm,seeds);info['enumerated']=enumerated;return rows,info

def unavailable(firm,config):
    response=get(config['search'])
    text=BeautifulSoup(response.text,'html.parser').get_text(' ',strip=True)
    if 'maintenance' in response.url or 'job search is currently unavailable' in text.lower():raise CollectionError('Official job search is under maintenance')
    raise CollectionError('Search reached but complete enumeration adapter not yet validated; previous snapshot preserved')

REGISTRY={
 'Robert Half':{'adapter':'sitemap','sitemap':'https://www.roberthalf.com/content/roberthalf.sitemap.us-external-job-details-sitemap.xml','pattern':r'/us/en/job/'},
 'Insight Global':{'adapter':'unavailable','search':'https://insightglobal.com/jobs/search/all/all?page=1&size=100'},
 'TEKsystems':{'adapter':'sitemap','sitemap':'https://careers.teksystems.com/us/en/sitemap_index.xml','pattern':r'/us/en/job/'},
 'Apex Systems':{'adapter':'unavailable','search':'https://www.apexsystems.com/search-results-usa'},
 'Kforce':{'adapter':'unavailable','search':'https://www.kforce.com/search-jobs/'},
 'Randstad':{'adapter':'sitemap','sitemap':'https://www.randstadusa.com/sitemaps/us/sitemap-jobs.xml','pattern':r'/jobs/\d+/'},
 'Aerotek':{'adapter':'sitemap','sitemap':'https://jobs.aerotek.com/us/en/sitemap_index.xml','pattern':r'/us/en/job/'},
 'Beacon Hill':{'adapter':'sitemap','sitemap':'https://bhsg.com/jobs/job_listing-sitemap.xml','pattern':r'/jobs/job/'},
 'Judge Group':{'adapter':'unavailable','search':'https://www.judge.com/jobs/'},
 'Brooksource':{'adapter':'sitemap','sitemap':'https://jobs.brooksource.com/jobs/job_listing-sitemap.xml','pattern':r'/jobs/job/'},
 'Genesis10':{'adapter':'jobdiva','account':'bbjdnwry580gs8b24ge36gcyw8pwpu006c13v960z6xbeg9upecbf81tivitxrw0'},
 'Experis/Manpower':{'adapter':'unavailable','search':'https://www.experis.com/en/search'},
 'Addison Group':{'adapter':'unavailable','search':'https://addisongroup.com/jobs/'},
 'Vaco':{'adapter':'vaco'},
 'The Select Group':{'adapter':'unavailable','search':'https://jobs.selectgroup.com/career-seekers/careers/'},
 'Signature Consultants':{'adapter':'unavailable','search':'https://dexian.com/jobs/'},
 'Collabera':{'adapter':'unavailable','search':'https://collabera.com/find-a-job/'},
 'Mindlance':{'adapter':'jobdiva','account':'7fjdnw91pq69jlvngz1gp518iugamw00c66623tmx447r7e3lkr3gqqpqjhpy8mo'},
 'Motion Recruitment':{'adapter':'unavailable','search':'https://motionrecruitment.com/tech-jobs'},
}
ADAPTERS={'sitemap':sitemap_collect,'jobdiva':jobdiva,'vaco':vaco,'unavailable':unavailable}
def collect(firm,route):
    start=now()
    try:
        rows,info=ADAPTERS[REGISTRY[firm]['adapter']](firm,REGISTRY[firm]);result={'ok':True,'rows':rows,'info':info}
    except Exception as e:result={'ok':False,'error':str(e)[:2000]}
    result.update(firm=firm,route=route,started_at=start,completed_at=now());print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True);return result
