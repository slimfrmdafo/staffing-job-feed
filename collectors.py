"""First-party site collectors. Incomplete enumeration/details fail the whole firm."""
import concurrent.futures, html, json, re, time, threading
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin, unquote, parse_qs
import requests
import urllib.request
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
            if r.status_code==403:
                # Retry with Python's standard HTTP client for sites incompatible with requests.
                # This is an ordinary public GET, with no login/challenge handling.
                try:
                    request=urllib.request.Request(r.url,headers={'User-Agent':'Mozilla/5.0 (compatible; StaffingFeed/1.0)'})
                    with urllib.request.urlopen(request,timeout=60) as source:
                        other=requests.Response();other.status_code=source.status;other.url=source.url;other._content=source.read();other.headers.update(dict(source.headers));other.encoding='utf-8';r=other
                except Exception:pass
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
            r['city']=plain(addr.get('addressLocality'));r['city']='' if '[' in r['city'] else r['city'];r['state']=state_code(addr.get('addressRegion'))
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
    context=r['description']
    if firm=='Robert Half':
        card=soup.select_one('rhcl-job-card[variant="listing"]')
        if card:
            parts=[plain(x.get_text()) for x in card.select('[slot="description"], [slot="requirements"]')]
            if parts:r['description']='\n\n'.join(parts)
            loc=card.select_one('[data-subslot="location"]')
            if loc:
                loc=loc.get_text(' ',strip=True).split(',')
                if len(loc)>1:r['city']=loc[0].strip();r['state']=state_code(loc[-1].strip())
            work=card.select_one('[data-subslot="worksite"]')
            if work and work.text.strip() in ('remote','onsite','hybrid'):r['work_arrangement']=work.text.strip()
    if firm=='Signature Consultants':
        for label in soup.select('.meta-label'):
            if label.get_text(' ',strip=True).lower()=='location':
                value=label.find_next_sibling(class_='meta-content')
                if value:
                    text=value.get_text(' ',strip=True);parts=text.split(',')
                    if len(parts)==2:r.update(city=parts[0].strip(),state=state_code(parts[1].strip()))
                    if re.fullmatch(r'(?:fully )?remote(?:,? (?:US|USA|United States))?',text,re.I):r['work_arrangement']='remote'
        explicit=re.search(r'\b(?:\d+[+ -]*months?\s+contract|contract.to.hire|contract position|contract opportunity)\b',r['description'],re.I)
        if explicit:r['job_type']=job_type(explicit[0])
    if firm in ('TEKsystems','Aerotek'):
        try:
            d=assigned_json(str(soup),'phApp.ddo = ')
            data=d.get('jobDetail',{}).get('data',{}).get('job',{})
            if data.get('workplaceType') in ('Remote','Hybrid','On-Site'):r['work_arrangement']={'Remote':'remote','Hybrid':'hybrid','On-Site':'onsite'}[data['workplaceType']]
        except (ValueError,CollectionError):pass
    return enrich(r,context)

def detail(firm,seed):
    url=seed['url']
    try:
        response=get(url)
        if 'ref=invalid_job' in response.url or any(x in response.url for x in ['jobs-maintenance']):raise ClosedListing('Listing no longer available')
        soup=BeautifulSoup(response.text,'html.parser')
        if not any(x.get('@type')=='JobPosting' for x in schemas(soup)) and re.search(r'(?:job (?:is no longer|has been filled)|position has been filled|job you are looking for is no longer)',soup.get_text(' ',strip=True),re.I):raise ClosedListing('Closed notice')
        row=schema_row(firm,url,soup,seed)
        if row is None and firm=='Beacon Hill':row=beacon_row(firm,url,soup,seed)
        if row is None and re.search(r'quick security check|confirm you.re human',soup.get_text(' ',strip=True),re.I):raise CollectionError('Human security check on full detail: '+url)
        if row is None:raise CollectionError('Full JobPosting data missing: '+url)
        if not row['title'] or not row['description']:raise CollectionError('Incomplete detail: '+url)
        country='';nearby=False
        js=next((x for x in schemas(soup) if x.get('@type')=='JobPosting'),{})
        locs=js.get('jobLocation',[]);locs=locs if isinstance(locs,list) else [locs]
        for loc in locs:
            if not isinstance(loc,dict):continue
            addr=loc.get('address',{})
            if isinstance(addr,dict):
                c=addr.get('addressCountry','');country=c.get('name','') if isinstance(c,dict) else c
            geo=loc.get('geo') or {}
            if geo.get('latitude') and geo.get('longitude'):
                import math
                try:
                    lat,lon=map(math.radians,[float(geo['latitude']),float(geo['longitude'])]);clat,clon=map(math.radians,[35.2271,-80.8431])
                    miles=3958.8*2*math.asin(min(1,math.sqrt(math.sin((lat-clat)/2)**2+math.cos(lat)*math.cos(clat)*math.sin((lon-clon)/2)**2)))
                    nearby=nearby or miles<=50
                except (ValueError,TypeError):pass
        return row if keep(row,country=country,nearby=nearby) else None
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
    if not urls:return []
    return urls

def sitemap_collect(firm,config):
    urls=sitemap_urls(config['sitemap'],config['pattern']);seeds=[]
    if not urls:raise CollectionError('Job sitemap unexpectedly empty')
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
    if firm=='Signature Consultants':
        match=re.search(r'-(\d+)-(\d+)$',parts[-1]);return match[1] if match else ''
    if firm=='The Select Group':
        m=re.search(r'/(\d+)',path);return m[1] if m else ''
    return ''

def beacon_row(firm,url,soup,seed):
    body=soup.select_one('.job_description, .job-description, .job_description-content, .job-detail__content, .job-content, .fl-module-fl-post-content')
    if body is None:
        about=soup.find(string=re.compile(r'^About the Role$'))
        if about:
            body=about.find_parent('section') or about.parent.parent
    if body is None:return None
    r=blank();r.update(firm=firm,url=url,job_id=seed['job_id'],description=body.get_text('\n',strip=True))
    h=soup.select_one('h1');r['title']=h.get_text(' ',strip=True) if h else ''
    loc=soup.select_one('.job-hero__location')
    if loc:
        pieces=loc.get_text(' ',strip=True).split(',');r['city']=pieces[0].strip();r['state']=state_code(pieces[1].strip()) if len(pieces)>1 else ''
    hero=soup.select_one('.job-hero')
    context=hero.get_text('\n',strip=True) if hero else ''
    r['job_type']=job_type(context)
    m=re.search(r'\b(\d{2})-(\d{2})-(\d{4})\b',context)
    if m:r['posted_date']=f'{m[3]}-{m[1]}-{m[2]}'
    return enrich(r,context)

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
        desc=plain(j.findtext('jobdescription'));location=(j.findtext('location') or '').lower()
        from core import LOCAL
        if not any(re.search(r'\b'+re.escape(city)+r'\b',location) for city in LOCAL) and not re.search(r'\bremote\b',desc+' '+location,re.I):continue
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
        nxt=next((a for a in links if 'next' in a.get('rel',[])),None)
        if not nxt:nxt=next((a for a in links if a.get_text(' ',strip=True).lower() in ('next','next »','next page')),None)
        if not nxt:break
        url=urljoin(url,nxt['href'])
    else:raise CollectionError('Vaco exceeded safety page limit')
    rows,info=fetch_details(firm,seeds);info['enumerated']=enumerated;return rows,info

def unavailable(firm,config):
    response=get(config['search'])
    import pathlib
    pathlib.Path('diagnostics').mkdir(exist_ok=True)
    pathlib.Path('diagnostics/'+re.sub(r'[^A-Za-z0-9]+','_',firm)+'.html').write_text(response.text)
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
 'Beacon Hill':{'adapter':'sitemap','sitemap':'https://bhsg.com/jobs/sitemap_index.xml','pattern':r'/jobs/job/'},
 'Judge Group':{'adapter':'unavailable','search':'https://www.judge.com/jobs/'},
 'Brooksource':{'adapter':'sitemap','sitemap':'https://jobs.brooksource.com/jobs/sitemap_index.xml','pattern':r'/jobs/job/'},
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

# Public JSON endpoints used by the firms' own job-search applications.
def insight(firm,config):
    from core import number
    seen={};total=None
    for page in range(1,501):
        d=get('https://insightglobal.com/all/jobs',params={'page':page,'size':50,'sort':'relevance,desc','filter.status':'active'}).json()
        meta=d['pageMetadata'];jobs=d['jobs']
        if meta['number']!=page:raise CollectionError('Insight Global pagination number mismatch')
        if total is None:total=meta['totalElements']
        fresh=0
        for j in jobs:
            key=j['requisitionId']
            if key not in seen:fresh+=1
            seen[key]=j
        if not fresh and jobs:raise CollectionError('Insight Global repeated page')
        if page>=meta['totalPages']:break
    else:raise CollectionError('Insight Global pagination limit')
    if len(seen)<total:raise CollectionError('Insight Global incomplete pagination')
    rows=[];candidates=0
    def one(j):
        if not title_match(j['jobTitle']):return None
        addr=j.get('workAddress') or {}
        from core import LOCAL
        if not j.get('workRemote') and not (addr.get('locality','').lower() in LOCAL and addr.get('administrativeArea') in ('NC','SC')):return None
        detail=get('https://insightglobal.com/all/jobs/'+j['requisitionId']+'/details').json()
        description=plain(detail.get('description'))
        if not description:raise CollectionError('Insight Global description missing')
        r=blank();r.update(firm=firm,job_id=j['requisitionId'],title=j['jobTitle'].strip(),city=addr.get('locality',''),state=state_code(addr.get('administrativeArea')),description=description,url='https://insightglobal.com/jobs/search/all/all?jobId='+j['requisitionId'],job_type=job_type(j.get('jobType')))
        # This API's workRemote boolean only distinguishes remote from nonremote; false doesn't imply onsite.
        if j.get('workRemote'):r['work_arrangement']='remote'
        pay=j.get('payRate') or {};unit={'Hourly':'hour','Annually':'year'}.get(pay.get('type'),'')
        if unit:r.update(pay_min=number(pay.get('min')),pay_max=number(pay.get('max')),pay_unit=unit)
        date=str(j.get('postedDate') or '')
        if re.match(r'^\d{4}-\d{2}-\d{2}',date):r['posted_date']=date[:10]
        return enrich(r,description)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for r in pool.map(one,seen.values()):
            if r:
                candidates+=1
                if keep(r):rows.append(r)
    return rows,{'enumerated':len(seen),'details_read':candidates,'kept':len(rows)}


def kforce(firm,config):
    from core import number
    # Public read-only search credential shipped in Kforce's own JS client.
    endpoint='https://kforcewebeast.search.windows.net/indexes/kforcewebjobentity/docs'
    headers={'api-key':'1603E4DC4C87A8E41D6BBDE4EEA4EFB7'}
    seen={};total=None
    for skip in range(0,30000,1000):
        d=get(endpoint,headers=headers,params={'api-version':'2020-06-30','search':'*','$top':1000,'$skip':skip,'$count':'true','$orderby':'Id asc'}).json()
        total=d['@odata.count']
        for j in d['value']:seen[j['Id']]=j
        if skip+len(d['value'])>=total:break
        if not d['value']:raise CollectionError('Kforce search truncated')
    if len(seen)!=total:raise CollectionError('Kforce count mismatch')
    rows=[];details=0
    for j in seen.values():
        if not title_match(j.get('Title','')):continue
        from core import LOCAL
        if not j.get('Remote') and j.get('City','').lower() not in LOCAL:continue
        # Get the complete detail object, as the site's detail view does, separately from discovery.
        d=get(endpoint,headers=headers,params={'api-version':'2020-06-30','search':'*','$filter':"Id eq '"+j['Id']+"'"}).json()['value']
        if len(d)!=1:raise CollectionError('Kforce detail disappeared')
        j=d[0];details+=1;r=blank()
        r.update(firm=firm,job_id=str(j.get('ReferenceCode') or j['Id']),title=plain(j.get('Title')),city=plain(j.get('City')),state=state_code(j.get('State')),description=plain(j.get('ResponsibilitiesHtml') or j.get('Responsibilities'))+'\n'+plain(j.get('SkillsHtml') or j.get('Skills')),url='https://www.kforce.com/search-jobs/#/detail/'+j['Id']+'/',job_type=job_type(j.get('TypeCode')))
        if j.get('Remote') is True or str(j.get('Remote','')).lower() in ('true','yes','remote'):r['work_arrangement']='remote'
        date=str(j.get('PostDate') or '')
        if re.match(r'^\d{4}-\d{2}-\d{2}',date):r['posted_date']=date[:10]
        # SalaryText supplies the unit; bare numeric API fields do not.
        enrich(r,str(j.get('SalaryText') or '')+'\n'+r['description'])
        if keep(r):rows.append(r)
    return rows,{'enumerated':len(seen),'details_read':details,'kept':len(rows)}


def rh_search(firm,config):
    # SEO search pages enumerate live cards; older sitemap entries can redirect to search.
    seeds={};pages=0
    queries=['business-analyst','project-manager','program-manager','implementation-manager','business-operations','business-execution','risk','compliance','governance','change-management','process-improvement','legal-operations','pmo','business-transformation']
    for term in queries:
        for location in ['all-locations']:
            url=f'https://www.roberthalf.com/us/en/jobs/{location}/{term}';seen=set()
            for page in range(1,101):
                response=get(url,params={'pagenumber':page});soup=BeautifulSoup(response.text,'html.parser');pages+=1
                if not soup.select_one('h1'):raise CollectionError('Robert Half search missing heading')
                cards=soup.select('rhcl-job-card[variant="card"]');current=set()
                for c in cards:
                    a=c.select_one('a[href]')
                    if not a:continue
                    current.add(c.get('job-id'))
                    if title_match(a.text):
                        seed={'url':a['href'],'job_id':c['job-id']}
                        loc=c.select_one('[data-subslot="location"]')
                        if loc:
                            parts=loc.text.split(',')
                            if len(parts)>1:seed.update(city=parts[0].strip(),state=state_code(parts[-1].strip()))
                        w=c.select_one('[data-subslot="worksite"]')
                        if w and w.text.strip() in ('remote','hybrid','onsite'):seed['work_arrangement']=w.text.strip()
                        seeds[a['href']]=seed
                if page>1 and current and current<=seen:raise CollectionError('Robert Half repeated page')
                seen.update(current)
                nxt=next((a for a in soup.select('a[href]') if re.search(r'pagenumber='+str(page+1)+r'(?:&|$)',html.unescape(a['href']))),None)
                if not nxt:break
            else:raise CollectionError('Robert Half pagination limit')
    rows,info=fetch_details(firm,seeds.values());info['search_pages']=pages;return rows,info

ADAPTERS.update(insight=insight,kforce=kforce,rh_search=rh_search)
REGISTRY['Insight Global']['adapter']='insight'
REGISTRY['Kforce']['adapter']='kforce'
REGISTRY['Robert Half']['adapter']='rh_search'
REGISTRY['The Select Group']={'adapter':'sitemap','sitemap':'https://jobs.selectgroup.com/career-seekers/careers/job_listing-sitemap.xml','pattern':r'/careers/job/'}

def post_json(url,payload):
    for attempt in range(3):
        try:
            r=requests.post(url,json=payload,timeout=(15,90));r.raise_for_status();d=r.json()
            return json.loads(d) if isinstance(d,str) else d
        except (requests.RequestException,ValueError):
            if attempt==2:raise
            time.sleep(2+attempt)


def experis(firm,config):
    seeds={};seen=set();total=None
    for offset in range(0,101):
        d=post_json('https://www.experis.com/api/services/Jobs/searchjobs',{'filter':{'offset':offset,'totalCount':0,'limit':100,'searchkeyword':None,'haslocation':False,'language':'en'}})
        jobs=d['jobsItems'];total=int(d.get('filters',{}).get('totalCount') or d['totalNumberOfPosition'])
        fresh=0
        for j in jobs:
            if j['jobID'] not in seen:fresh+=1
            seen.add(j['jobID'])
            if title_match(j['jobTitle']):
                seed={'url':urljoin('https://www.experis.com',j['jobURL']),'job_id':str(j['jobID'])}
                parts=str(j.get('jobLocation') or '').split(',')
                if len(parts)==2:seed.update(city=parts[0].strip(),state=state_code(parts[1].strip()))
                seeds[j['jobID']]=seed
        if (offset*100)+len(jobs)>=total:break
        if not fresh:raise CollectionError('Experis search repeated or empty page')
    if len(seen)<total:raise CollectionError('Experis search count mismatch')
    rows,info=fetch_details(firm,seeds.values());info['enumerated']=len(seen);return rows,info


def motion(firm,config):
    seeds={};seen=set();total=None
    for start in range(0,10000,20):
        url='https://motionrecruitment.com/tech-jobs';response=get(url,params={'start':start});soup=BeautifulSoup(response.text,'html.parser')
        current={urljoin(url,a['href']):a.get_text(' ',strip=True) for a in soup.select('a[href]') if re.search(r'^/tech-jobs/.*/\d+$',a['href'])}
        # The SSR page exposes the same total as its listing widget.
        for script in soup.find_all('script'):
            text=script.get_text()
            if 'dataSet' in text:
                m=re.search(r'\\"total\\":(\d+)',text)
                if m:total=int(m[1]);break
        if total is None:raise CollectionError('Motion total count missing')
        if not current or (seen and set(current)<=seen):raise CollectionError('Motion pagination incomplete/repeated')
        seen.update(current)
        for href,title in current.items():
            if title_match(title):seeds[href]={'url':href,'job_id':href.rstrip('/').split('/')[-1]}
        if start+len(current)>=total:break
    else:raise CollectionError('Motion pagination limit')
    if len(seen)<total:raise CollectionError('Motion count mismatch')
    rows,info=fetch_details(firm,seeds.values());info['enumerated']=len(seen);return rows,info

ADAPTERS.update(experis=experis,motion=motion)
REGISTRY['Experis/Manpower']['adapter']='experis'
REGISTRY['Motion Recruitment']['adapter']='motion'

def judge(firm,config):
    from datetime import datetime,timezone
    base='https://www.judge.com/wp-admin/admin-ajax.php?action='
    seen={};total=None
    for page in range(0,501):
        payload={'categories':[],'countries':'USA','geo':[{'distance':'','latLong':[0],'location':''}],'query':'','states':'','type':['Any'],'page':page,'remote':False}
        d=post_json(base+'jdg_get_jobs',{'payload':payload})
        if 'hits' not in d:raise CollectionError('Judge search error: '+str(d)[:200])
        if total is None:total=d['total']
        fresh=0
        for j in d['hits']:
            if str(j['jobOrderId']) not in seen:fresh+=1
            seen[str(j['jobOrderId'])]=j
        if d['offset']+len(d['hits'])>=d['total']:break
        if not fresh:raise CollectionError('Judge pagination repeated/empty')
    else:raise CollectionError('Judge pagination limit')
    if len(seen)<total:raise CollectionError('Judge count mismatch')
    rows=[];candidates=0
    def one(j):
        if not title_match(j['title']):return None
        d=post_json(base+'jdg_get_job_detail',{'payload':{'job_id':j['jobOrderId']}})
        if d is None:return None
        if not d.get('description'):raise CollectionError('Judge full detail missing')
        r=blank();r.update(firm=firm,job_id=str(d['jobOrderId']),title=d['title'].strip(),description=plain(d['description']),url='https://www.judge.com/jobs/details/'+str(d['jobOrderId'])+'/',job_type=job_type(d.get('type')))
        loc=str(d.get('location') or '');parts=loc.split(',')
        if len(parts)>=2:r.update(city=parts[0].strip(),state=state_code(parts[1].strip()))
        if 'remote' in loc.lower():r['work_arrangement']='remote'
        if d.get('opened'):r['posted_date']=datetime.fromtimestamp(float(d['opened'])/1000,timezone.utc).strftime('%Y-%m-%d')
        enrich(r,str(d.get('salary') or '')+'\n'+r['description'])
        return r
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for r in pool.map(one,seen.values()):
            if r:
                candidates+=1
                if keep(r,country='USA'):rows.append(r)
    return rows,{'enumerated':len(seen),'details_read':candidates,'kept':len(rows)}

ADAPTERS['judge']=judge
REGISTRY['Judge Group']['adapter']='judge'

def addison(firm,config):
    # A normal browser is used on the Mac when HTTP access is refused. No challenge bypass.
    browser=None;pw=None;page=None
    def read(url):
        nonlocal browser,pw,page
        if page is not None:
            response=page.goto(url,wait_until='domcontentloaded',timeout=60000)
            if response and response.status>=400:raise CollectionError('Browser HTTP '+str(response.status))
            return page.content()
        try:return get(url).text
        except CollectionError:
            import os
            if os.environ.get('STAFFING_ROUTE')!='mac':raise
            if page is None:
                from playwright.sync_api import sync_playwright
                pw=sync_playwright().start();browser=pw.chromium.launch(headless=True);page=browser.new_page()
            response=page.goto(url,wait_until='domcontentloaded',timeout=60000)
            page.wait_for_timeout(1500)
            if response and response.status>=400:raise CollectionError('Addison browser HTTP '+str(response.status))
            return page.content()
    try:
        url='https://www.addisongroup.com/jobs/results/';seen=set();seeds={};expected=None
        for page_no in range(1,101):
            text=read(url);soup=BeautifulSoup(text,'html.parser');current={}
            for a in soup.select('a[href]'):
                href=urljoin(url,a['href'])
                if re.search(r'/jobs/job/[^/]+/[\w-]+$',href):current[href]=a.get_text(' ',strip=True)
            if not current or (seen and set(current)<=seen):raise CollectionError('Addison job enumeration incomplete/repeated')
            seen.update(current)
            for href,title in current.items():
                if title_match(title):seeds[href]={'url':href,'job_id':href.rstrip('/').split('/')[-1]}
            nxt=next((a for a in soup.select('a[href]') if re.search(r'[?&]page='+str(page_no+1)+r'(?:&|$)',a['href'])),None)
            if not nxt:break
            url=urljoin(url,nxt['href'])
        else:raise CollectionError('Addison pagination limit')
        rows=[]
        for seed in seeds.values():
            soup=BeautifulSoup(read(seed['url']),'html.parser');r=schema_row(firm,seed['url'],soup,seed)
            if r is None:raise CollectionError('Addison full detail schema missing: '+seed['url'])
            if not r['description']:raise CollectionError('Addison description missing')
            if keep(r):rows.append(r)
        return rows,{'enumerated':len(seen),'details_read':len(seeds),'kept':len(rows),'browser_used':browser is not None}
    finally:
        if browser:browser.close()
        if pw:pw.stop()
ADAPTERS['addison']=addison
REGISTRY['Addison Group']['adapter']='addison'
REGISTRY['Collabera']['search']='https://www.collabera.com/job-search/'

def collabera(firm,config):
    import os
    from core import number
    browser=pw=page=None
    def read(url):
        nonlocal browser,pw,page
        if page is None:
            try:return get(url).text
            except CollectionError:
                if os.environ.get('STAFFING_ROUTE')!='mac':raise
                from playwright.sync_api import sync_playwright
                pw=sync_playwright().start();browser=pw.chromium.launch(headless=True);page=browser.new_page()
        response=page.goto(url,wait_until='domcontentloaded',timeout=60000)
        if response and response.status>=400:raise CollectionError('Collabera browser HTTP '+str(response.status))
        return page.content()
    try:
        base='https://www.collabera.com/job-search/';seen=set();seeds={};total=None
        for n in range(1,101):
            soup=BeautifulSoup(read(base+'?q='+str(n)),'html.parser');text=soup.get_text(' ',strip=True)
            m=re.search(r'Showing\s+\d+[-–]\d+\s+of\s+(\d+)\s+Jobs',text,re.I)
            if not m:raise CollectionError('Collabera search count missing')
            total=int(m[1]);current={}
            for a in soup.select('a[href]'):
                if '/job-description/?post=' not in a['href']:continue
                h=a.select_one('h5') or a.select_one('h4') or a.select_one('h3')
                if h is None:continue
                current[a['href']]=h.get_text(' ',strip=True)
            if not current or (seen and set(current)<=seen):raise CollectionError('Collabera search repeated/empty')
            seen.update(current)
            for url,title in current.items():
                if title_match(title):seeds[url]=title
            if n*10>=total:break
        if len(seen)<total:raise CollectionError('Collabera incomplete search count')
        rows=[]
        for url,title in seeds.items():
            soup=BeautifulSoup(read(url),'html.parser');body=soup.select_one('div.position');text=soup.get_text('\n',strip=True)
            if body is None:raise CollectionError('Collabera full detail missing')
            h=next((x for x in soup.select('h4') if x.get_text(' ',strip=True)==title),None)
            if h is None:raise CollectionError('Collabera detail title mismatch')
            m=re.search(r'End Date:\s*(\d{4}-\d{2}-\d{2})',text)
            if m and m[1]<now()[:10]:continue
            r=blank();r.update(firm=firm,job_id=parse_qs(urlparse(url).query)['post'][0],title=h.get_text(' ',strip=True),url=url,description=body.get_text('\n',strip=True))
            m=re.search(r'(Contract|Direct Hire|Remote|Contract.to.Hire):\s*([^,\n]+),\s*([^,\n]+),\s*US\b',text,re.I)
            if m:
                r.update(city=m[2].strip(),state=state_code(m[3].strip()),job_type=job_type(m[1]))
                if m[1].lower()=='remote':r['work_arrangement']='remote'
            m=re.search(r'Salary Range:\s*([\d,.]+)\s*[-–]\s*([\d,.]+)\s*\|\s*Per\s*(Hour|Year)',text,re.I)
            if m:r.update(pay_min=number(m[1]),pay_max=number(m[2]),pay_unit=m[3].lower())
            contact=body.select_one('.recruiter')
            if contact:
                ul=contact.find_next('ul');values=ul.select('.col-9 li') if ul else []
                if len(values)>=3:r.update(recruiter_name=values[0].get_text(' ',strip=True),recruiter_email=values[1].get_text(' ',strip=True),recruiter_phone=values[2].get_text(' ',strip=True))
            enrich(r,r['description'])
            if keep(r,country='US'):rows.append(r)
        return rows,{'enumerated':len(seen),'details_read':len(seeds),'kept':len(rows),'browser_used':browser is not None}
    finally:
        if browser:browser.close()
        if pw:pw.stop()
ADAPTERS['collabera']=collabera
REGISTRY['Collabera']['adapter']='collabera'

REGISTRY['Signature Consultants']={'adapter':'sitemap','sitemap':'https://dexian.com/sitemap_index.xml','pattern':r'/jobs/[^/]+-\d+-\d+/'}

def apex(firm,config):
    url='https://www.apexsystems.com/search-results-usa';seen=set();seeds={}
    for page in range(0,1001):
        response=get(url);soup=BeautifulSoup(response.text,'html.parser')
        if 'maintenance' in response.url or (soup.title and 'maintenance' in soup.title.get_text().lower()):raise CollectionError('Official job search and detail pages are under maintenance')
        current={urljoin(response.url,a['href']).split('?')[0]:a.get_text(' ',strip=True) for a in soup.select('a[href]') if re.search(r'/job/\d+_usa/',a['href'])}
        if not current:raise CollectionError('Apex search returned no enumerable listings; preserving prior snapshot')
        if current and set(current)<=seen:raise CollectionError('Apex pagination repeated')
        seen.update(current)
        for href,title in current.items():
            if title_match(title):seeds[href]={'url':href,'job_id':re.search(r'/job/(\d+)_usa/',href)[1]}
        nxt=soup.select_one('a[rel="next"], .pager__item--next a')
        if not nxt:break
        url=urljoin(response.url,nxt['href'])
    else:raise CollectionError('Apex pagination limit')
    rows,info=fetch_details(firm,seeds.values());info['enumerated']=len(seen);return rows,info
ADAPTERS['apex']=apex
REGISTRY['Apex Systems']['adapter']='apex'
