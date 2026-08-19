from __future__ import annotations

import json, re, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

SITES={
 'AP':'https://diofe.portal.ap.gov.br',
 'ES':'https://ioes.dio.es.gov.br',
 'GO':'https://diariooficial.abc.go.gov.br',
}
OUT=Path('quick_autopage_results'); OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36'


def get(s,u,timeout=90,attempts=3):
 last=None
 for i in range(attempts):
  try:
   r=s.get(u,timeout=timeout,verify=False)
   if r.status_code in {429,500,502,503,504}: raise RuntimeError(f'HTTP {r.status_code}')
   return r
  except Exception as e:
   last=e; time.sleep(1+i)
 raise RuntimeError(f'{u}: {last}')


def dateval(v):
 if v is None:return None
 x=str(v)
 m=re.search(r'(\d{4})-(\d{2})-(\d{2})',x)
 if m:return '-'.join(m.groups())
 m=re.search(r'(\d{2})/(\d{2})/(\d{4})',x)
 if m:return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
 return None


def walk(x):
 if isinstance(x,dict):
  yield x
  for v in x.values(): yield from walk(v)
 elif isinstance(x,list):
  for v in x: yield from walk(v)


def editions(obj):
 out=[]
 for d in walk(obj):
  lower={str(k).lower():k for k in d}
  idk=next((lower[k] for k in ['id','edicao_id','id_edicao','idedicao'] if k in lower),None)
  dk=next((lower[k] for k in ['data','data_publicacao','datapublicacao','publication_date','dataedicao'] if k in lower),None)
  if idk is None or dk is None:continue
  dt=dateval(d.get(dk)); iv=d.get(idk)
  if dt and str(iv).isdigit():out.append({'id':int(iv),'date':dt,'obj':d})
 uniq={ (x['id'],x['date']):x for x in out }
 return sorted(uniq.values(),key=lambda z:(z['date'],z['id']))


def matter_count(html):
 soup=BeautifulSoup(html,'html.parser'); ids=set()
 for a in soup.select('a.linkMateria, a[identificador], a[data-materia-id], a[data-id]'):
  for k in ['identificador','data-materia-id','data-id']:
   v=a.get(k)
   if v and str(v).isdigit():ids.add(str(v))
 ids.update(re.findall(r'publicacoes_ver_conteudo/(\d+)',html))
 return len(ids)


def html_test(s,base,eid):
 urls=[f'{base}/portal/visualizacoes/html/{eid}',f'{base}/portal/visualizacoes/html/{eid}/',f'{base}/html/{eid}.html']
 best={'status':None,'matter_count':0,'url':urls[0],'length':0}
 for u in urls:
  try:
   r=get(s,u,60,2); c=matter_count(r.text) if r.status_code==200 else 0
   cand={'status':r.status_code,'content_type':r.headers.get('content-type',''),'matter_count':c,'url':u,'length':len(r.content)}
   if c>0:return cand
   if cand['status']==200 and best['status']!=200:best=cand
  except Exception as e:
   best={'url':u,'error':f'{type(e).__name__}: {e}','matter_count':0}
 return best


def first_true_binary(items,fn):
 lo,hi=0,len(items)-1;ans=None;tests=[]
 while lo<=hi:
  mid=(lo+hi)//2; item=items[mid]; val=fn(item); tests.append({'index':mid,'id':item['id'],'date':item['date'],'result':val})
  if val.get('matter_count',0)>0: ans=(mid,item,val);hi=mid-1
  else:lo=mid+1
 # verify local window and guard against non-monotonicity
 if ans:
  start=max(0,ans[0]-25);end=min(len(items),ans[0]+2)
  for i in range(start,end):
   v=fn(items[i]);tests.append({'index':i,'id':items[i]['id'],'date':items[i]['date'],'result':v,'window':True})
   if v.get('matter_count',0)>0:
    ans=(i,items[i],v);break
 return ans,tests


def run(st,base):
 s=requests.Session();s.trust_env=False;s.headers.update({'User-Agent':UA,'Accept':'*/*','Referer':base+'/'})
 res={'state':st,'base':base}
 u=f'{base}/apifront/portal/edicoes/ultimas_edicoes.json?subtheme=false'
 try:
  r=get(s,u,120,4);res['endpoint_status']=r.status_code;res['content_type']=r.headers.get('content-type');res['bytes']=len(r.content)
  obj=r.json(); items=editions(obj);res['edition_count']=len(items)
  res['earliest_issue']=items[0] if items else None;res['latest_issue']=items[-1] if items else None
  if items:
   cache={}
   def f(it):
    if it['id'] not in cache:cache[it['id']]=html_test(s,base,it['id'])
    return cache[it['id']]
   ans,tests=first_true_binary(items,f);res['html_tests']=tests
   res['first_publication_html']={'id':ans[1]['id'],'date':ans[1]['date'],'result':ans[2]} if ans else None
   # check 2010 and 2021 representative/first available issues
   for year in ['2010','2021']:
    ys=[x for x in items if x['date'].startswith(year+'-')]
    res[f'{year}_issue_count']=len(ys)
    if ys:
     res[f'{year}_first_issue']=ys[0]
     res[f'{year}_first_html']=f(ys[0])
     res[f'{year}_last_issue']=ys[-1]
     res[f'{year}_last_html']=f(ys[-1])
 except Exception as e:res['error']=f'{type(e).__name__}: {e}'
 Path(OUT/f'{st}.json').write_text(json.dumps(res,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
 print(st,json.dumps({k:res.get(k) for k in ['edition_count','earliest_issue','first_publication_html','error']},ensure_ascii=False,default=str),flush=True)
 return res

allres=[run(st,b) for st,b in SITES.items()]
Path(OUT/'summary.json').write_text(json.dumps(allres,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
