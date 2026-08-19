from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT=Path('manual_review_results'); OUT.mkdir(exist_ok=True)
BASE='https://www.diario.pi.gov.br/doe/'
ENDPOINT=BASE+'Api/listardiarios.json'
S=requests.Session(); S.trust_env=False; S.headers.update({'User-Agent':'Mozilla/5.0','Accept':'*/*','Referer':BASE})

def post(data):
    last=None
    for i in range(4):
        try:
            r=S.post(ENDPOINT,data=data,timeout=120,verify=False)
            if r.status_code in {429,500,502,503,504}: raise RuntimeError(f'HTTP {r.status_code}')
            r.raise_for_status(); return r
        except Exception as e:last=e;time.sleep(i+1)
    raise RuntimeError(last)

rows=[]; total=None; start=0; length=500
while total is None or start<total:
    obj=post({'draw':'1','start':str(start),'length':str(length)}).json()
    total=int(obj.get('recordsFiltered') or obj.get('recordsTotal') or 0)
    batch=obj.get('data') or []
    if not batch:break
    rows.extend(batch); start+=len(batch)
    if len(batch)<length:break
parsed=[]
for row in rows:
    if not isinstance(row,list) or len(row)<3:continue
    m=re.search(r'href=["\']([^"\']+)',str(row[0]),re.I)
    if not m:continue
    try:dt=datetime.strptime(str(row[2]).strip(),'%d/%m/%Y').date().isoformat()
    except:continue
    parsed.append({'date':dt,'edition':str(row[1]).strip(),'pdf_url':urljoin(BASE,m.group(1))})
parsed.sort(key=lambda x:(x['date'],x['edition'],x['pdf_url']))
years={}
for x in parsed:years[x['date'][:4]]=years.get(x['date'][:4],0)+1

def verify(u):
    try:
        r=S.get(u,headers={'Range':'bytes=0-4095'},stream=True,timeout=180,verify=False)
        first=next(r.iter_content(4096),b'')
        return {'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'content_length':r.headers.get('content-length'),'is_pdf':first.startswith(b'%PDF-')}
    except Exception as e:return {'error':f'{type(e).__name__}: {e}','is_pdf':False}
res={'state':'PI','main_url':BASE,'api_url':ENDPOINT,'records_reported':total,'records_parsed':len(parsed),'earliest_issue':parsed[0] if parsed else None,'latest_issue':parsed[-1] if parsed else None,'year_counts':years,'covers_2010_2021':all(str(y) in years for y in range(2010,2022)),'earliest_pdf_verification':verify(parsed[0]['pdf_url']) if parsed else None,'latest_pdf_verification':verify(parsed[-1]['pdf_url']) if parsed else None}
(OUT/'PI.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
