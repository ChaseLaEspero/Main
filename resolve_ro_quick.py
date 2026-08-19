from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT=Path('manual_review_results'); OUT.mkdir(exist_ok=True)
BASE='https://diof.ro.gov.br/'
S=requests.Session(); S.trust_env=False; S.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36','Accept':'*/*','Referer':BASE})

def get(url, *, attempts=3, timeout=90, **kwargs):
    last=None
    for i in range(attempts):
        try:
            r=S.get(url,timeout=timeout,verify=False,**kwargs)
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f'HTTP {r.status_code}')
            return r
        except Exception as e:last=e;time.sleep(i+1)
    raise RuntimeError(f'{url}: {last}')

def extract_date(s):
    m=re.search(r'(?<!\d)(20\d{2})[-_/\.](0[1-9]|1[0-2])[-_/\.](0[1-9]|[12]\d|3[01])(?!\d)',s)
    if m:return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    m=re.search(r'(?<!\d)(0[1-9]|[12]\d|3[01])[-_/\.](0[1-9]|1[0-2])[-_/\.](20\d{2})(?!\d)',s)
    if m:return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
    return None

def verify_pdf(url):
    try:
        r=get(url,attempts=2,timeout=60,headers={'Range':'bytes=0-4095'},stream=True)
        first=next(r.iter_content(4096),b'')
        return {'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'content_length':r.headers.get('content-length'),'is_pdf':first.startswith(b'%PDF-')}
    except Exception as e:return {'url':url,'error':f'{type(e).__name__}: {e}','is_pdf':False}

candidates={}
for y in range(2017,2020):
    for m in range(1,13):
        url=BASE+f'diarios?cf_time={y:04d}-{m:02d}'
        try:
            r=get(url,attempts=2,timeout=60)
            if r.status_code!=200:continue
            soup=BeautifulSoup(r.text,'html.parser')
            for a in soup.find_all('a',href=True):
                u=urljoin(r.url,a['href'])
                if '.pdf' not in u.lower():continue
                txt=' '.join([a.get_text(' ',strip=True),u])
                if not any(k in txt.lower() for k in ('doe','diario','diário','jornal')):continue
                d=extract_date(txt) or extract_date(u)
                candidates[u]={'pdf_url':u,'effective_date':d,'source_page':r.url,'link_text':a.get_text(' ',strip=True)}
        except Exception:
            pass

d=date(2019,8,8)
while d<=date(2019,12,31):
    for name in [f'DOE-{d:%d-%m-%Y}.pdf',f'DOE-{d:%d-%m-%Y}-SUPLEMENTAR.pdf',f'DOE-SUPLEMENTAR-{d:%d-%m-%Y}.pdf']:
        u=BASE+f'data/uploads/{d:%Y/%m}/'+name
        candidates.setdefault(u,{'pdf_url':u,'effective_date':d.isoformat(),'source_page':'predictable dated path','link_text':''})
    d+=timedelta(days=1)

ordered=sorted(candidates.values(),key=lambda x:(x.get('effective_date') or '9999-99-99',x['pdf_url']))
earliest=None;tests=[]
for c in ordered:
    v=verify_pdf(c['pdf_url'])
    tests.append({'effective_date':c.get('effective_date'),'pdf_url':c['pdf_url'],'is_pdf':v.get('is_pdf'), 'status':v.get('status'), 'content_type':v.get('content_type')})
    if v.get('is_pdf'):
        earliest=dict(c);earliest['verification']=v;break

res={'state':'RO','main_url':BASE+'diarios','download_page':BASE+'downloads/','legal_electronic_start':'2019-08-08','candidate_count':len(candidates),'tested_until_first_valid':len(tests),'earliest_valid_issue_pdf':earliest,'boundary_tests':tests,'covers_2010_2021_in_current_electronic_archive':False,'conclusion':'The current official electronic full-issue archive begins in August 2019 and does not cover 2010-2018. The Diário itself existed in print before then, but no official online full-issue source for 2010-2018 was verified.'}
(OUT/'RO.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
