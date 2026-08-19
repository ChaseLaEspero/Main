from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

OUT=Path('manual_review_results'); OUT.mkdir(exist_ok=True)
BASE='https://diariooficial.cepe.com.br/'
ENDPOINT=BASE+'diariooficial/public/search'
S=requests.Session(); S.trust_env=False; S.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36','Accept':'application/json, text/plain, */*','Content-Type':'application/json;charset=UTF-8','Referer':BASE+'diariooficialweb/'})

def post(payload,attempts=3):
    last=None
    for i in range(attempts):
        try:
            r=S.post(ENDPOINT,json=payload,timeout=120,verify=False)
            if r.status_code in {429,500,502,503,504}:raise RuntimeError(f'HTTP {r.status_code}')
            return r
        except Exception as e:last=e;time.sleep(i+1)
    raise RuntimeError(last)

def payload(start:date,end:date,word:str,first=0,max_results=100):
    a=start.strftime('%d-%m-%Y'); b=end.strftime('%d-%m-%Y')
    return {
        'first':first,'maxResults':max_results,'restricoes':{},'order':{},
        'data':date.today().isoformat()+'T00:00:00.000Z',
        'minDate':start.isoformat()+'T00:00:00.000Z',
        'maxDate':end.isoformat()+'T23:59:59.999Z',
        'palavras':word,'dataInicial':a,'dataFinal':b,
        'intervaloAno':a+'-'+b,'codigoDiario':'1'
    }

def summarize_response(r):
    out={'http_status':r.status_code,'content_type':r.headers.get('content-type',''),'length':len(r.content),'preview':r.text[:1000]}
    try:
        obj=r.json(); out['json_type']=type(obj).__name__
        if isinstance(obj,dict):
            out['keys']=list(obj.keys())
            for k in ('rowCount','total','count','recordsTotal','recordsFiltered','status','code','errors'):
                if k in obj:out[k]=obj[k]
            for k in ('list','data','content','results','itens'):
                if isinstance(obj.get(k),list):
                    out['list_key']=k;out['list_len']=len(obj[k]);out['list_sample']=obj[k][:2]
                    break
        out['json']=obj
    except Exception as e:out['json_error']=f'{type(e).__name__}: {e}'
    return out

def has_results(summary):
    if summary.get('http_status')!=200:return False
    for k in ('rowCount','total','count','recordsTotal','recordsFiltered'):
        try:
            if int(summary.get(k) or 0)>0:return True
        except:pass
    return int(summary.get('list_len') or 0)>0

words=['estado','governo','secretaria','concurso']
year_tests=[]
years_with_results=[]
for y in range(1936,2027):
    found=None
    for word in words:
        try:
            s=summarize_response(post(payload(date(y,1,1),date(y,12,31),word,max_results=5)))
        except Exception as e:
            s={'error':f'{type(e).__name__}: {e}'}
        year_tests.append({'year':y,'word':word,'summary':{k:v for k,v in s.items() if k!='json'}})
        if has_results(s):
            found={'year':y,'word':word,'summary':s};years_with_results.append(found);break
    print('year',y,'found',bool(found),flush=True)

earliest_year=years_with_results[0]['year'] if years_with_results else None
earliest_word=years_with_results[0]['word'] if years_with_results else None
# Locate the first date with at least one hit using monthly then daily windows.
earliest_date=None; earliest_result=None
if earliest_year:
    month_hit=None
    for m in range(1,13):
        start=date(earliest_year,m,1)
        end=date(earliest_year+1,1,1)-timedelta(days=1) if m==12 else date(earliest_year,m+1,1)-timedelta(days=1)
        s=summarize_response(post(payload(start,end,earliest_word,max_results=20)))
        if has_results(s):month_hit=(start,end,s);break
    if month_hit:
        d=month_hit[0]
        while d<=month_hit[1]:
            s=summarize_response(post(payload(d,d,earliest_word,max_results=20)))
            if has_results(s):earliest_date=d.isoformat();earliest_result=s;break
            d+=timedelta(days=1)
# Test the project period explicitly.
project_tests=[]
for y in range(2010,2022):
    success=False;best=None
    for word in words:
        s=summarize_response(post(payload(date(y,1,1),date(y,12,31),word,max_results=5)))
        project_tests.append({'year':y,'word':word,'summary':{k:v for k,v in s.items() if k!='json'}})
        if has_results(s):success=True;best={'word':word,'summary':s};break
    project_tests.append({'year':y,'has_machine_readable_results':success,'best':best})
res={'state':'PE','main_url':BASE+'diariooficialweb/','search_api':ENDPOINT,'publication_detail_api':BASE+'diariooficial/public/busca-avancada/consultarMateriaBuscaAvancada','earliest_year_with_results':earliest_year,'earliest_date_with_results':earliest_date,'earliest_word_used':earliest_word,'earliest_result':earliest_result,'years_with_results':[{'year':x['year'],'word':x['word'],'rowCount':x['summary'].get('rowCount'),'list_len':x['summary'].get('list_len')} for x in years_with_results],'project_years_with_results':[x['year'] for x in project_tests if x.get('has_machine_readable_results')],'covers_2010_2021':all(any(x.get('year')==y and x.get('has_machine_readable_results') for x in project_tests) for y in range(2010,2022)),'year_tests':year_tests,'project_tests':project_tests}
(OUT/'PE.json').write_text(json.dumps(res,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print(json.dumps({k:res.get(k) for k in ('earliest_year_with_results','earliest_date_with_results','project_years_with_results','covers_2010_2021')},ensure_ascii=False,indent=2))
