"""Conservative extraction of explicitly posted qualifications and contacts."""
import re
EMAIL=re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
PHONE=re.compile(r'(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)')
CERT=re.compile(r'\b(?:PMP|CAPM|FINRA|SIE|Series\s+(?:6|7|9|10|24|63|65|66)|CBAP|CCBA|CAMS|CISA|CISM|CISSP|CRISC|CSM|CSPO|CCMP|CRC|CPC|CCS|RHIA|RHIT|AAPC|AHIMA|ITIL|PRINCE2|CPA|CIA|CFE|CRCM|CRMA|FRM|PRM|CHC|CHPC|CHPS|CPIM|CSCP|NERC|Lean Six Sigma|Six Sigma (?:Green|Black) Belt|SAFe|PMI[- ](?:PBA|ACP|SP)|Prosci|Certified Scrum Master|Epic\s+Lumens)\b',re.I)
OPTIONAL=re.compile(r'preferred|nice.to.have|desir(?:ed|able)|not required|a plus|bonus|highly valued|beneficial',re.I)
REQUIRED_HEADING=re.compile(r'^(?:required|mandatory|minimum|essential|must[- ]have)\s+(?:qualifications?|skills?|experience|certifications?|credentials?)\b|^certifications?\s+required\b',re.I)
OTHER_HEADING=re.compile(r'^(?:nice.to.have|preferred|desired|additional qualifications|job description|responsibilities|key responsibilities|benefits|about us|about the company|what.s in it for me|role priorities)\b',re.I)

def required_certifications(text):
    lines=[re.sub(r'\s+',' ',x).strip(' \t•*-') for x in re.split(r'\n+|;|(?<=[.!?])\s+',text)]
    result=[];required=False;skip_next=False
    for i,line in enumerate(lines):
        if skip_next:skip_next=False;continue
        if not line:continue
        if REQUIRED_HEADING.search(line):required=True
        elif OTHER_HEADING.search(line):required=False
        if re.search(r'certification\s+(?:is\s+)?required\s+(?:through|from|by)$',line,re.I) and i+1<len(lines):line+=' '+lines[i+1];skip_next=True
        relevant=CERT.search(line) or re.search(r'\b(?:Project Management|professional|active|current|valid)\s+certification|\bCertification required through\b',line,re.I)
        if not relevant or OPTIONAL.search(line):continue
        if CERT.search(line) and not re.search(r'certif|credential|licens|registrat|professional \(PMP\)|^\s*(?:PMP|CAPM|CISA|CISM|CISSP|CSM)\b',line,re.I):continue
        if line.startswith(','):continue
        explicit=bool(re.search(r'\b(?:required|mandatory|must (?:have|hold|possess|maintain))\b',line,re.I))
        if explicit or required:
            if re.fullmatch(r'(?:Required|Mandatory|Minimum)\s+(?:Qualifications|Certifications|Skills)',line,re.I):continue
            result.append(line.rstrip('.'))
    return '; '.join(dict.fromkeys(result))

def contact_fields(text):
    out={};selected=None
    for match in EMAIL.finditer(text):
        address=match[0].rstrip('.,;')
        if re.search(r'hrsupport|^hr@|privacy|accommod|accessibility|humanresources|eeoc|benefit|noreply|no-reply|webmaster|^support@',address,re.I):continue
        before=text[max(0,match.start()-220):match.start()]
        previous_lines=[x.strip() for x in before.splitlines() if x.strip()]
        following_lines=[x.strip() for x in text[match.end():match.end()+180].splitlines() if x.strip()]
        nearest=(previous_lines[-1] if previous_lines else '')+' '+(following_lines[0] if following_lines else '')
        if re.search(r'accommod|accessib|disabilit|privacy|(?:report|suspect).{0,25}(?:fraud|scam)',nearest,re.I):continue
        if not re.search(r'recruit|contact|hiring manager|resume|reach|email|talent acquisition|regards|office|apply',before,re.I):continue
        selected=match;out['recruiter_email']=address;break
    names=list(re.finditer(r'(?i:recruiter(?: name)?|contact(?: name)?|hiring (?:manager|contact))\s*:\s*([A-Z][A-Za-z\'.-]+(?:[ \t]+[A-Z][A-Za-z\'.-]+){1,3})(?=\s*[;\n,]|\s*$)',text))
    if names:out['recruiter_name']=names[0][1].strip()
    if selected:
        near=text[max(0,selected.start()-240):selected.end()+160]
        if 'recruiter_name' not in out:
            m=re.search(r'(?:Regards|Sincerely|Thanks(?: and Regards)?)\s*[,\n]+\s*([A-Z][a-z\'.-]+(?:\s+[A-Z][a-z\'.-]+){1,2})(?=\s+(?:Executive|Recruiter|Talent|Senior|Technical|Account))',near)
            if m:out['recruiter_name']=m[1]
            m=re.search(r'(?:reach out to|contact)\s+([A-Z][a-z\'.-]+(?:\s+[A-Z][a-z\'.-]+){1,2})\s+at\s*$',text[max(0,selected.start()-100):selected.start()],re.I)
            if m:out['recruiter_name']=m[1]
        phone=PHONE.search(near)
        if phone:out['recruiter_phone']=phone[0]
    elif names:
        near=text[names[0].start():names[0].end()+180];phone=PHONE.search(near)
        if phone:out['recruiter_phone']=phone[0]
    return out

def usable_phone(value):
    value=str(value or '').strip();return value if 10<=len(re.sub(r'\D','',value))<=15 else ''

# Each amount may carry its own scale and unit (e.g. $87K - $140K USD Annual,
# or $87,800/yr - $119,000/yr). Missing units stay missing.
def posted_pay(text):
    amount=r'\$\s*([\d,]+(?:\.\d+)?)\s*([kK]?)'
    unit=r'(?:/|per\s+)?\s*(hourly|hour|hr|yearly|year|yr|annum|annual)\b'
    pattern=amount+r'(?:\s*'+unit+r')?\s*[-–—]\s*'+amount+r'(?:\s*(?:USD|US dollars)\s*)?(?:\s*'+unit+r')?'
    candidates=list(re.finditer(pattern,text,re.I))
    for m in candidates:
        before=text[max(0,m.start()-180):m.start()]
        # Dollar amounts in budgets, bonuses or project examples aren't base pay ranges.
        if not re.search(r'base pay|salary|compensation|pay range|pay rate|hourly rate|wage',before,re.I):continue
        lo=float(m[1].replace(',',''))*(1000 if m[2] else 1);hi=float(m[4].replace(',',''))*(1000 if m[5] else 1)
        if hi<lo:continue
        stated=m[6] or m[3] or ''
        if not stated and re.search(r'\b(?:annual|yearly|per year)\b.{0,100}\b(?:base|salary|pay)\b|\b(?:salary|pay)\b.{0,60}\b(?:annual|yearly|per year)\b',before,re.I):stated='year'
        if not stated and re.search(r'\bhourly\b.{0,60}\b(?:rate|pay|wage)\b',before,re.I):stated='hour'
        kind='hour' if stated.lower() in ('hour','hourly','hr') else ('year' if stated else '')
        return {'pay_min':str(int(lo)) if lo.is_integer() else str(lo),'pay_max':str(int(hi)) if hi.is_integer() else str(hi),'pay_unit':kind}
    return {}
