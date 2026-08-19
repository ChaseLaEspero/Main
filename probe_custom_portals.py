from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT=Path('custom_portal_probe');OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
SITES={
 'AL':{'base':'https://diario.imprensaoficial.al.gov.br/','known':['apinova/api/editions/published?page=1']},
 'PI':{'base':'https://www.diario.pi.gov.br/doe/','known':['Api/listardiarios.json']},
 'SC':{'base':'https://portal.doe.sea.sc.gov.br/','known':['apis/jornal/?page=1&perPage=12&dtStart=2011-10-03%2000:00:00&dtEnd=2026-08-19%2023:59:59']},
 'PE':{'base':'https://diariooficial.cepe.com.br/diariooficialweb/','known':[]},
 'RR':{'base':'https://www.imprensaoficial.rr.gov.br/app/_inicial/','known':[]},
 'TO':{'base':'https://diariooficial.to.gov.br/','known':[]},
 'RO':{'base':'https://diof.ro.gov.br/','known':[]},
}

PATTERNS=[
 re.compile(r'https?://[^"\'\s<>]+'),
 re.compile(r'/(?:api|apis|apinova|Api|ajax|consulta|pesquisa|busca|diario|diarios|jornal|materia|materias|editions|edicoes|publicacoes)[A-Za-z0-9_?&=./%{}:\-]*'),
 re.compile(r'(?:api|apis|apinova|Api)/[A-Za-z0-9_?&=./%{}:\-]+'),
]

def req(s,u,timeout=60):
 for i in range(3):
  try:
   r=s.get(u,timeout=timeout,verify=False)
   if r.status_code in (429,500,502,503,504):raise RuntimeError(r.status_code)
   return r
  except Exception as e:
   last=e;time.sleep(i+1)
 raise RuntimeError(f'{u}: {last}')

def extract(text):
 vals=[];seen=set()
 for pat in PATTERNS:
  for m in pat.finditer(text):
   v=m.group(0).strip('"\'()[],;')
   low=v.lower()
   if any(k in low for k in ('api','jornal','diario','edi','publica','materia','busca','pesquisa','pdf','html','xml','json')) and v not in seen:
    seen.add(v);vals.append(v)
 return vals

def summarize_json(obj):
 res={'type':type(obj).__name__}
 if isinstance(obj,dict):
  res['keys']=list(obj.keys())
  for k,v in obj.items():
   if isinstance(v,list):res[f'list_{k}_len']=len(v);res[f'list_{k}_sample']=v[:2]
   elif isinstance(v,(str,int,float,bool)) or v is None:res[k]=v
 elif isinstance(obj,list):res['len']=len(obj);res['sample']=obj[:2]
 return res

def run(st,cfg):
 s=requests.Session();s.headers.update({'User-Agent':UA,'Accept':'*/*','Referer':cfg['base']});s.trust_env=False
 out={'state':st,'base':cfg['base'],'errors':[],'known':[],'scripts':[],'discovered':[]}
 try:
  r=req(s,cfg['base']);out['home_status']=r.status_code;out['home_url']=r.url;out['home_ct']=r.headers.get('content-type');out['home_len']=len(r.content);html=r.text
 except Exception as e:
  out['errors'].append(f'home {type(e).__name__}: {e}');html=''
 soup=BeautifulSoup(html,'html.parser')
 scripts=[]
 for tag in soup.select('script[src]'):
  u=urljoin(cfg['base'],tag.get('src'))
  if u not in scripts:scripts.append(u)
 out['home_extract']=extract(html)[:300]
 all_found=set(out['home_extract'])
 for idx,u in enumerate(scripts[:40]):
  item={'url':u}
  try:
   r=req(s,u,90);item['status']=r.status_code;item['ct']=r.headers.get('content-type');item['len']=len(r.content)
   txt=r.text;found=extract(txt);item['found']=found[:500];all_found.update(found)
   (OUT/f'{st}_script_{idx:02d}.txt').write_text(txt,encoding='utf-8',errors='ignore')
  except Exception as e:item['error']=f'{type(e).__name__}: {e}'
  out['scripts'].append(item)
 for path in cfg['known']:
  u=urljoin(cfg['base'],path);item={'url':u}
  try:
   r=req(s,u,90);item['status']=r.status_code;item['ct']=r.headers.get('content-type');item['len']=len(r.content);item['preview']=r.text[:3000]
   try:item['json_summary']=summarize_json(r.json())
   except:pass
  except Exception as e:item['error']=f'{type(e).__name__}: {e}'
  out['known'].append(item)
 out['discovered']=sorted(all_found)[:2000]
 (OUT/f'{st}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
 print(st,'home',out.get('home_status'),'scripts',len(out['scripts']),'found',len(out['discovered']),flush=True)
 return out

rows=[]
for st,cfg in SITES.items():
 try:rows.append(run(st,cfg))
 except Exception as e:rows.append({'state':st,'fatal':f'{type(e).__name__}: {e}'})
(OUT/'summary.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
