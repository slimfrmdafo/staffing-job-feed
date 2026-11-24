"""Strict feed contract, conservative extraction and lossless snapshot merging."""
import csv, html, io, json, re, math
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from metadata import required_certifications,contact_fields,posted_pay

COLUMNS = 'firm,job_id,title,client_company,city,state,work_arrangement,job_type,contract_length,pay_min,pay_max,pay_unit,posted_date,url,recruiter_name,recruiter_email,recruiter_phone,required_experience,required_certifications,description'.split(',')
ROLE = re.compile(r'business.{0,25}analy|project.{0,12}manag|program.{0,12}manag|implementation.{0,12}manag|business.{0,10}operat|business.{0,10}execution|operations?.{0,15}(?:analyst|consultant|specialist|manager)|on.?boarding|risk|business.{0,12}control|control.{0,10}(?:analyst|consultant|specialist|manager)|compliance|regulatory|governance|\baml\b|\bkyc\b|change.{0,12}manag|process.{0,12}improv|legal.{0,10}operat|\bpmo\b|business.{0,12}transform', re.I)
EXCLUDE = re.compile(r'\b(nurse|clinical|physician|therapist|warehouse|welder|electrician|mechanic|carpenter|software engineer|software developer|\bINTL\b|full.stack|front.end developer|back.end developer|construction project|civil engineer)\b',re.I)
STATES = dict(x.split(':') for x in 'Alabama:AL|Alaska:AK|Arizona:AZ|Arkansas:AR|California:CA|Colorado:CO|Connecticut:CT|Delaware:DE|Florida:FL|Georgia:GA|Hawaii:HI|Idaho:ID|Illinois:IL|Indiana:IN|Iowa:IA|Kansas:KS|Kentucky:KY|Louisiana:LA|Maine:ME|Maryland:MD|Massachusetts:MA|Michigan:MI|Minnesota:MN|Mississippi:MS|Missouri:MO|Montana:MT|Nebraska:NE|Nevada:NV|New Hampshire:NH|New Jersey:NJ|New Mexico:NM|New York:NY|North Carolina:NC|North Dakota:ND|Ohio:OH|Oklahoma:OK|Oregon:OR|Pennsylvania:PA|Rhode Island:RI|South Carolina:SC|South Dakota:SD|Tennessee:TN|Texas:TX|Utah:UT|Vermont:VT|Virginia:VA|Washington:WA|West Virginia:WV|Wisconsin:WI|Wyoming:WY|District of Columbia:DC'.split('|'))
# Explicitly named locations are included even where a city center is beyond 50 miles.
LOCAL = {'charlotte','indian land','wesley chapel','rock hill','fort mill','concord','gastonia','mooresville','hickory','huntersville','cornelius','davidson','belmont','mount holly','matthews','mint hill','monroe','indian trail','waxhaw','pineville','stallings','weddington','harrisburg','kannapolis','denver','lincolnton','statesville','salisbury','lancaster','york','clover','tega cay','lake wylie','kings mountain','shelby','dallas','bessemer city','lowell','stanley','mount pleasant','troutman','locust','midland','wingate','marshville','maiden','newton','catawba','chester','richburg','pageland'}

def now(): return datetime.now(timezone.utc).isoformat()
def plain(v):
    if v is None:return ''
    return BeautifulSoup(html.unescape(str(v)), 'html.parser').get_text('\n',strip=True)
def state_code(v):
    v=str(v or '').strip()
    return v if v in STATES.values() else STATES.get(v,'')
def title_match(title): return bool(ROLE.search(title) and not EXCLUDE.search(title))
def blank():return dict.fromkeys(COLUMNS,'')
def number(v):
    try:
        n=float(str(v).replace(',','').replace('$',''));return str(int(n)) if n.is_integer() else str(n)
    except (ValueError,TypeError):return ''
def job_type(v):
    v=str(v or '').lower().replace('_',' ').replace('-',' ')
    if re.search(r'temp.*hire|contract.*hire|contract.*regular|contract.*perm|temp.*perm',v):return 'contract-to-hire'
    if re.search(r'contract|temporary|^temp$',v):return 'contract'
    if re.search(r'permanent|direct hire|^perm$',v):return 'permanent'
    return ''
def enrich(row, context=''):
    """Extract only explicit statements; do not guess unknown metadata."""
    text=row['description']; ctx=context+'\n'+text
    if not row['work_arrangement']:
        if re.search(r'\bhybrid\b(?![- ](?:methodology|approach|agile|waterfall|cloud))',context,re.I):row['work_arrangement']='hybrid'
        elif re.search(r'\b(?:fully remote|100\s*%\s*remote|remote position|remote role|workplace type\s*remote)\b',ctx,re.I):row['work_arrangement']='remote'
        elif re.search(r'\b(?:onsite|on.site)\b',context,re.I):row['work_arrangement']='onsite'
    if not row['job_type']:
        m=re.search(r'(?:job type|employment type|employee type|position type|opportunity type)\s*[:\n]?\s*([^\n]{2,60})',ctx,re.I)
        if m:row['job_type']=job_type(m[1])
        if not row['job_type']:
            m=re.search(r'\b(contract.to.hire|temp.to.perm|\d+\+?[- ]month contract|contract opportunity|contract position|permanent position|direct hire)\b',ctx,re.I)
            if m:row['job_type']=job_type(m[0])
    duration=r'(\d+(?:\s*[-–]\s*\d+)?\+?\s*(?:months?|weeks?|years?))'
    m=re.search(r'(?:duration|contract length|assignment length|contract term)\s*[:–-]?\s*(?:initial(?:ly)?\s*)?'+duration+r'\b',ctx,re.I)
    if not m:
        m=re.search(r'\b'+duration+r'\s*[- ]?\s*(?:(?:W-?2|temporary)\s+)?(?:contract|assignment|opportunity)\b(?!\s+(?:experience|management|operations|negotiation))',ctx,re.I)
    if m:row['contract_length']=m[1]
    m=re.search(r'\b\d+\+?(?:\s*[-–]\s*\d+)?\s+years?(?:\s+of)?\s+(?:relevant\s+|professional\s+)?experience\b',text,re.I)
    if m:row['required_experience']=m[0]
    if not row['pay_unit']:
        m=re.search(r'\$\s*([\d,]+(?:\.\d+)?)\s*(?:k)?\s*[-–]\s*\$?\s*([\d,]+(?:\.\d+)?)\s*(k)?\s*(?:/|per\s+)?\s*(hour|hr|hourly|year|annum|annual)',ctx,re.I)
        if m:
            scale=1000 if m[3] else 1; row.update(pay_min=number(float(m[1].replace(',',''))*scale),pay_max=number(float(m[2].replace(',',''))*scale),pay_unit='hour' if m[4].lower() in ('hour','hr','hourly') else 'year')
    # Contact extraction requires an explicit recruiter/contact line to avoid EEO contacts.
    m=re.search(r'(?:recruiter|recruiting contact|contact name)\s*[:\n]\s*([^\n]{3,80})',text,re.I)
    if m:row['recruiter_name']=m[1].strip()
    m=re.search(r'(?:send (?:your )?resum[eé]|contact (?:your recruiter|me)|reach (?:me|out)|recruiter email)[^\n]{0,160}?([\w.+-]+@[\w.-]+\.[a-z]{2,})',text,re.I)
    if m:row['recruiter_email']=m[1]
    m=re.search(r'(?:Client|Client Company|End Employer)\s*:\s*([^\n]{3,100})',text,re.I)
    if m and not re.search(r'confidential|our client|fortune|financial institution|company in|undisclosed|^bank$|^client$|^healthcare organization$|^large|^leading|^major',m[1],re.I):row['client_company']=m[1].strip()
    m=re.search(r'\b(PMP|CAPM|CBAP|CCBA|CISA|CRISC|CAMS|CPA|CSM|Prosci)(?:\s+certification)?\s+(?:is\s+)?required\b',text,re.I)
    if m:row['required_certifications']=m[0]
    m=re.search(r'(?:recruiter phone|contact phone|call me at)\s*[:\n]?\s*(\+?1?[-. (]*\d{3}[-. )]*\d{3}[-. ]*\d{4})',text,re.I)
    if m:row['recruiter_phone']=m[1]
    if not row['pay_min'] and not row['pay_max']:
        for key,value in posted_pay(ctx).items():
            if value and not row[key]:row[key]=value
    cert=required_certifications(text)
    if cert:row['required_certifications']=cert
    for key,value in contact_fields(text).items():
        if value and not row[key]:row[key]=value
    return row

def keep(row, country='', nearby=False):
    if not title_match(row['title']):return False
    local=nearby or (row['city'].lower().strip() in LOCAL and row['state'] in ('NC','SC'))
    # A US address/explicit US remote eligibility is required for global listings.
    remote=row['work_arrangement']=='remote' and (row['state'] in STATES.values() or country in ('US','USA','United States') or re.search(r'\b(?:United States|US[- ]based|U\.S\.|remote.{0,15}USA|USA.{0,15}remote)\b',row['description'],re.I))
    if not (local or remote):return False
    if row['pay_unit'] and (row['pay_max'] or row['pay_min']):
        annual=float(row['pay_max'] or row['pay_min'])*(2080 if row['pay_unit']=='hour' else 1)
        if annual<60000:return False
    return True

def validate(rows):
    seen=set()
    for r in rows:
        if set(r)!=set(COLUMNS):raise ValueError('CSV columns do not match contract')
        for k in ('firm','job_id','title','url'):
            if not isinstance(r[k],str) or not r[k]:raise ValueError('Missing required '+k)
        if not r['url'].startswith('https://'):raise ValueError('Non-HTTPS job URL')
        key=(r['firm'],r['job_id'])
        if key in seen:raise ValueError('Duplicate firm + job_id')
        seen.add(key)
        for key,allowed in [('work_arrangement',{'','remote','hybrid','onsite'}),('job_type',{'','contract','contract-to-hire','permanent'}),('pay_unit',{'','hour','year'})]:
            if r[key] not in allowed:raise ValueError('Invalid '+key)
        if r['state'] and r['state'] not in STATES.values():raise ValueError('Invalid state')
        if r['posted_date']:datetime.strptime(r['posted_date'],'%Y-%m-%d')
        for key in ('pay_min','pay_max'):
            if r[key] and (not re.fullmatch(r'\d+(?:\.\d+)?',r[key]) or not math.isfinite(float(r[key]))):raise ValueError('Invalid pay')

def csv_text(rows):
    validate(rows);stream=io.StringIO(newline='');w=csv.DictWriter(stream,fieldnames=COLUMNS);w.writeheader();w.writerows(rows);return stream.getvalue()

def merge(state, attempts):
    """Rebased on latest remote state before every compare-and-swap publish."""
    state=json.loads(json.dumps(state));state.setdefault('firms',{})
    for a in attempts:
        f=state['firms'].setdefault(a['firm'],{'rows':[],'attempts':{}})
        route=a['route'];old=f['attempts'].get(route,{})
        if a['started_at']>old.get('started_at',''):f['attempts'][route]={k:v for k,v in a.items() if k!='rows'}
        if a['ok'] and a['started_at']>f.get('snapshot_at',''):
            validate(a['rows']);f.update(rows=a['rows'],snapshot_at=a['started_at'],completed_at=a['completed_at'],snapshot_route=route)
    return state
