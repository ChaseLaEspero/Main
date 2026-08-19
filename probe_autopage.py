from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

OUT=Path('autopage_probe'); OUT.mkdir(exist_ok=True)
SITES={
 'AP':'https://diofe.portal.ap.gov.br',
 'ES':'https://ioes.dio.es.gov.br',
 'GO':'https://diariooficial.abc.go.gov.br',
}
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36'


def get(s,u,timeout=45,attempts=3):
 last=None
 for i in range(attempts):
  try:
   r=s.get(u,timeout=timeout,verify=False)
   if r.status_code in (429,500,502,503,504): raise RuntimeError(f'HTTP {r.status_code}')
   return r
  except Exception as e:
   last=e; time.sleep(i+1)
 raise RuntimeError(f'{u}: {last}')


def normdate(v):
 if not v:return None
 x=str(v)
 for pat in [r'(\d{4})-(\d{2})-(\d{2})',r'(\d{2})/(\d{2})/(\d{4})']:
  m=re.search(pat,x)
  if m:
   if len(m.group(1))==4:return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
   return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
 return None


def walk(x,path='$'):
 if isinstance(x,dict):
  yield path,x
  for k,v in x.items(): yield from walk(v,path+'.'+str(k))
 elif isinstance(x,list):
  for i,v in enumerate(x): yield from walk(v,f'{path}[{i}]')


def collect_editions(obj):
 out=[]
 for p,d in walk(obj):
  keys={str(k).lower():k for k in d}
  idk=next((keys[k] for k in ('id','edicao_id','id_edicao') if k in keys),None)
  dk=next((keys[k] for k in ('data','data_publicacao','datapublicacao','publication_date') if k in keys),None)
  if idk is not None and dk is not None:
   dt=normdate(d.get(dk))
   if dt and str(d.get(idk)).isdigit():
    out.append({'path':p,'id':int(d[idk]),'date':dt,'keys':list(d.keys()),'obj':d})
 # dedupe
 seen=set(); ans=[]
 for x in out:
  k=(x['id'],x['date'])
  if k not in seen:seen.add(k);ans.append(x)
 return ans


def date_payload(s,base,dt):
 urls=[
  f'{base}/apifront/portal/edicoes/edicoes_from_data/{dt}.json',
  f'{base}/apifront/portal/edicoes/edicoes_from_data/{dt}.json?subtheme=false',
 ]
 for u in urls:
  r=get(s,u,30,2)
  if r.status_code==200 and 'json' in r.headers.get('content-type','').lower():
   try:return u,r.json()
   except:pass
 return urls[-1],None


def matter_ids(raw):
 soup=BeautifulSoup(raw,'html.parser')
 ids=set()
 selectors='a.linkMateria, a[identificador], a[data-materia-id], a[data-id]'
 for a in soup.select(selectors):
  for k in ('identificador','data-materia-id','data-id'):
   v=a.get(k)
   if v and str(v).isdigit():ids.add(str(v))
 # endpoints/attributes sometimes embedded in JS
 ids.update(re.findall(r'publicacoes_ver_conteudo/(\d+)',raw))
 return ids


def html_check(s,base,eid):
 urls=[f'{base}/portal/visualizacoes/html/{eid}',f'{base}/portal/visualizacoes/html/{eid}/',f'{base}/html/{eid}.html']
 result=[]
 for u in urls:
  try:
   r=get(s,u,45,2); mids=matter_ids(r.text) if r.status_code==200 else set()
   result.append({'url':u,'status':r.status_code,'content_type':r.headers.get('content-type'),'length':len(r.content),'matter_ids':len(mids),'title':BeautifulSoup(r.text,'html.parser').title.get_text(' ',strip=True) if r.status_code==200 and BeautifulSoup(r.text,'html.parser').title else ''})
   if mids:return result[-1]
  except Exception as e:result.append({'url':u,'error':f'{type(e).__name__}: {e}'})
 return result[0] if result else {}


def find_years(s,base,start=1930,end=2026):
 hits={}
 # Probe 12 representative dates per year (1st, 5th, 15th of Jan/Apr/Jul/Oct)
 for y in range(start,end+1):
  found=[]
  for m in (1,4,7,10):
   for day in (1,5,15):
    try:
     _,obj=date_payload(s,base,f'{y:04d}-{m:02d}-{day:02d}')
     eds=collect_editions(obj) if obj else []
     if eds:
      found.extend(eds);break
    except:pass
   if found:break
  if found:hits[y]=found[:3]
 return hits


def scan_year(s,base,y):
 d=date(y,1,1); end=date(y,12,31); rows=[]
 while d<=end:
  try:
   _,obj=date_payload(s,base,d.isoformat()); eds=collect_editions(obj) if obj else []
   for e in eds:rows.append(e)
  except:pass
  d+=timedelta(days=1)
 # dedupe/sort
 uniq={ (x['id'],x['date']):x for x in rows }
 return sorted(uniq.values(),key=lambda x:(x['date'],x['id']))


def run(st,base):
 s=requests.Session();s.headers.update({'User-Agent':UA,'Accept':'*/*','Referer':base+'/'});s.trust_env=False
 res={'state':st,'base':base}
 u=f'{base}/apifront/portal/edicoes/ultimas_edicoes.json?subtheme=false'
 try:
  r=get(s,u,60,3);res['latest_status']=r.status_code;res['latest_ct']=r.headers.get('content-type');res['latest_len']=len(r.content)
  obj=r.json() if r.status_code==200 else None
  eds=collect_editions(obj) if obj else []
  res['latest_edition_count']=len(eds);res['latest_min_date']=min((x['date'] for x in eds),default=None);res['latest_max_date']=max((x['date'] for x in eds),default=None);res['latest_sample']=eds[:3]
 except Exception as e:res['latest_error']=f'{type(e).__name__}: {e}'
 years=find_years(s,base,1930,2026);res['years_with_probe_hits']=sorted(years);res['year_hit_samples']=years
 if years:
  first=min(years); exact=scan_year(s,base,first);res['first_probe_year']=first;res['first_year_count']=len(exact);res['first_date']=exact[0]['date'] if exact else None;res['first_date_editions']=exact[:5]
 # exact project-year daily scans for 2010 and first probable modern HTML years
 for y in sorted(set([2010,2017,2021,2022,2023]+([min(years)] if years else []))):
  exact=scan_year(s,base,y);res[f'year_{y}_count']=len(exact);res[f'year_{y}_first']=exact[0]['date'] if exact else None;res[f'year_{y}_last']=exact[-1]['date'] if exact else None
  if exact:
   res[f'year_{y}_first_html']=html_check(s,base,exact[0]['id'])
   res[f'year_{y}_last_html']=html_check(s,base,exact[-1]['id'])
 # Determine first edition with matter-level HTML by scanning editions from each hit year chronologically, concentrating on 2015-2026.
 first_html=None
 for y in range(2000,2027):
  if y not in years:continue
  exact=scan_year(s,base,y)
  # test first, middle, last then all if any seem modern
  candidates=[]
  if exact:
   candidates=[exact[0],exact[len(exact)//2],exact[-1]]
  any_html=False
  for e in candidates:
   h=html_check(s,base,e['id'])
   if h.get('matter_ids',0)>0:any_html=True;break
  if any_html:
   for e in exact:
    h=html_check(s,base,e['id'])
    if h.get('matter_ids',0)>0:
     first_html={'date':e['date'],'id':e['id'],'check':h};break
   if first_html:break
 res['first_matter_html']=first_html
 Path(OUT/f'{st}.json').write_text(json.dumps(res,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
 print(st,res.get('first_date'),res.get('first_matter_html'),flush=True)
 return res

allres=[]
for st,b in SITES.items():
 try:allres.append(run(st,b))
 except Exception as e:allres.append({'state':st,'fatal':f'{type(e).__name__}: {e}'})
Path(OUT/'summary.json').write_text(json.dumps(allres,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
