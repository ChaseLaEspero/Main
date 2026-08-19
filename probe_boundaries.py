from __future__ import annotations

import json
import math
import time
from pathlib import Path

import requests

OUT=Path('boundary_probe');OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36'


def sess(base):
 s=requests.Session();s.headers.update({'User-Agent':UA,'Accept':'*/*','Referer':base});s.trust_env=False;return s

def request(s,method,url,**kwargs):
 last=None
 for i in range(4):
  try:
   r=s.request(method,url,timeout=kwargs.pop('timeout',90),verify=False,**kwargs)
   if r.status_code in (429,500,502,503,504):raise RuntimeError(f'HTTP {r.status_code}')
   return r
  except Exception as e:last=e;time.sleep(i+1)
 raise RuntimeError(f'{method} {url}: {last}')

def dump_response(r):
 out={'status':r.status_code,'url':r.url,'content_type':r.headers.get('content-type'),'length':len(r.content),'preview':r.text[:5000]}
 try:out['json']=r.json()
 except:pass
 return out

res={}

# AL
base='https://diario.imprensaoficial.al.gov.br/'
s=sess(base);o={}
for name,method,url,kw in [
 ('published','GET',base+'apinova/api/editions/published?page=1',{}),
 ('search_empty','POST',base+'apinova/api/editions/searchES?page=1&bucket_size=10',{'json':{}}),
 ('search_wide','POST',base+'apinova/api/editions/searchES?page=1&bucket_size=100',{'json':{'data_inicio':'1900-01-01','data_fim':'2026-12-31'}}),
]:
 try:o[name]=dump_response(request(s,method,url,**kw))
 except Exception as e:o[name]={'error':f'{type(e).__name__}: {e}'}
res['AL']=o;Path(OUT/'AL.json').write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

# SC
base='https://portal.doe.sea.sc.gov.br/'
s=sess(base);o={}
queries={
 'wide_page1':'apis/jornal/?page=1&perPage=100&dtStart=1900-01-01%2000:00:00&dtEnd=2026-12-31%2023:59:59',
 'pre_2011':'apis/jornal/?page=1&perPage=100&dtStart=1900-01-01%2000:00:00&dtEnd=2011-10-02%2023:59:59',
 'boundary':'apis/jornal/?page=1&perPage=100&dtStart=2011-09-01%2000:00:00&dtEnd=2011-11-01%2023:59:59',
}
for name,path in queries.items():
 try:o[name]=dump_response(request(s,'GET',base+path))
 except Exception as e:o[name]={'error':f'{type(e).__name__}: {e}'}
# Infer last page and request it.
try:
 j=o['wide_page1']['json'];total=int(j.get('total') or 0);per=100;last=max(1,math.ceil(total/per));o['total']=total;o['last_page_num']=last
 o['wide_last']=dump_response(request(s,'GET',base+f'apis/jornal/?page={last}&perPage={per}&dtStart=1900-01-01%2000:00:00&dtEnd=2026-12-31%2023:59:59'))
except Exception as e:o['last_error']=f'{type(e).__name__}: {e}'
res['SC']=o;Path(OUT/'SC.json').write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

# PE
base='https://diariooficial.cepe.com.br/'
s=sess(base);o={}
for decade in range(1930,2030,10):
 try:o[f'dates_{decade}']=dump_response(request(s,'GET',base+f'diariooficial/public/datas?startDecade={decade}'))
 except Exception as e:o[f'dates_{decade}']={'error':f'{type(e).__name__}: {e}'}
# Test public metadata endpoints.
for name,url in [
 ('diarios',base+'diariooficial/public/diarios-public'),
 ('categorias',base+'diariooficial/public/busca-avancada/consultarCategoriasPai?codigoDiario=1'),
 ('anos',base+'diariooficial/public/consultarAnosMateriasPublicacoes'),
]:
 try:o[name]=dump_response(request(s,'GET',url))
 except Exception as e:o[name]={'error':f'{type(e).__name__}: {e}'}
# Try plausible search payloads.
payloads=[
 {},
 {'intervaloAno':{'anoInicial':1936,'anoFinal':1936},'codigoDiario':1,'pagina':0,'tamanhoPagina':20},
 {'anoInicial':1936,'anoFinal':1936,'codigoDiario':1,'page':0,'size':20},
 {'dataInicial':'1936-01-01','dataFinal':'1936-12-31','codigoDiario':1,'pagina':0,'tamanhoPagina':20},
]
for i,p in enumerate(payloads):
 try:o[f'search_{i}']=dump_response(request(s,'POST',base+'diariooficial/public/search',json=p))
 except Exception as e:o[f'search_{i}']={'error':f'{type(e).__name__}: {e}'}
res['PE']=o;Path(OUT/'PE.json').write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

# PI
base='https://www.diario.pi.gov.br/doe/'
s=sess(base);o={}
url=base+'Api/listardiarios.json'
# GET and DataTables POST variants
try:o['get']=dump_response(request(s,'GET',url))
except Exception as e:o['get']={'error':f'{type(e).__name__}: {e}'}
variants=[
 {'draw':'1','start':'0','length':'100'},
 {'draw':'1','start':'0','length':'100','dataInicio':'01/01/1900','dataFim':'31/12/2026'},
 {'draw':'1','start':'0','length':'100','dtInicio':'1900-01-01','dtFim':'2026-12-31'},
]
for i,data in enumerate(variants):
 try:o[f'post_{i}']=dump_response(request(s,'POST',url,data=data))
 except Exception as e:o[f'post_{i}']={'error':f'{type(e).__name__}: {e}'}
res['PI']=o;Path(OUT/'PI.json').write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

Path(OUT/'summary.json').write_text(json.dumps(res,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
for st,o in res.items():print(st, list(o), flush=True)
