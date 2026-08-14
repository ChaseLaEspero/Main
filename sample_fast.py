from __future__ import annotations

import csv, json, re, shutil, time, unicodedata, html as htmllib, zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import requests
from bs4 import BeautifulSoup

ROOT=Path('fast_samples'); ROOT.mkdir(exist_ok=True)
N=100; PER_ED=5
SITES={
 'AM': {'base':'https://diario.imprensaoficial.am.gov.br','toc':'/portal/visualizacoes/view_html_diario/{id}'},
 'BA': {'base':'https://www.doe.ba.gov.br','toc':'/html/{id}.html'},
}
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

def get(s,u,timeout=90,attempts=3):
 last=None
 for i in range(attempts):
  try:
   r=s.get(u,timeout=timeout)
   if r.status_code in {429,500,502,503,504}: raise RuntimeError(f'HTTP {r.status_code}')
   r.raise_for_status(); return r
  except Exception as e:
   last=e; time.sleep(i+1)
 raise RuntimeError(f'{u}: {last}')

def norm(s):
 s=htmllib.unescape(s or ''); s=unicodedata.normalize('NFKD',s); s=''.join(c for c in s if not unicodedata.combining(c)); s=s.casefold(); s=re.sub(r'[^0-9a-z\s]+',' ',s); return re.sub(r'\s+',' ',s).strip()

def clean(raw):
 soup=BeautifulSoup(raw,'html.parser')
 for t in soup(['script','style','noscript','svg']): t.decompose()
 for tr in soup.find_all('tr'):
  cells=[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'])]
  if cells: tr.replace_with('\t'.join(cells)+'\n')
 lines=[]
 for ln in soup.get_text('\n').splitlines():
  ln=re.sub(r'[ \t\xa0]+',' ',ln).strip()
  if ln: lines.append(ln)
 return '\n'.join(lines).strip()+'\n'

def matters(raw):
 soup=BeautifulSoup(raw,'html.parser'); out=[]; seen=set()
 for a in soup.select('a.linkMateria, a[identificador], a[data-materia-id]'):
  mid=a.get('identificador') or a.get('data-materia-id') or a.get('data-id')
  if mid and str(mid).isdigit() and str(mid) not in seen:
   mid=str(mid); seen.add(mid); out.append({'id':mid,'title':a.get_text(' ',strip=True)})
 return out

def principal(items):
 for x in items:
  sup=x.get('suplemento'); typ=str(x.get('tipo_edicao_nome') or '').lower()
  if sup in ('',None,0,'0',False) and 'extra' not in typ and 'suplement' not in typ: return x
 return items[0] if items else None

def pdf_issue(s,base,eid):
 u=f'{base}/portal/edicoes/download/{eid}'
 try:
  r=get(s,u,120,2); data=r.content
  if not data.startswith(b'%PDF-'): return '', 'not_public_pdf', 0, u
  d=fitz.open(stream=data,filetype='pdf'); text='\n'.join(p.get_text('text') for p in d); return text, ('ok' if text.strip() else 'no_text_layer'), d.page_count, u
 except Exception as e: return '',f'error:{type(e).__name__}',0,u

def cov(txt,pdf,n=5):
 a=norm(txt).split(); b=norm(pdf)
 if len(a)<n or not b: return None
 starts=list(range(len(a)-n+1))
 if len(starts)>150:
  step=len(starts)/150; starts=[int(i*step) for i in range(150)]
 sh=[' '.join(a[i:i+n]) for i in starts]
 return sum(x in b for x in sh)/len(sh)

def run(st,cfg):
 sd=ROOT/st; td=sd/'txt'; td.mkdir(parents=True,exist_ok=True)
 s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept':'*/*','Referer':cfg['base']+'/'})
 latest=get(s,cfg['base']+'/apifront/portal/edicoes/ultimas_edicoes.json?subtheme=false',60,3).json().get('itens') or []
 # Sort newest first, group principal entries, then if fewer than 20 use date endpoint by latest dates represented.
 eds=[]; seen=set()
 for x in latest:
  eid=str(x.get('id') or '')
  if eid and eid not in seen:
   seen.add(eid); eds.append(x)
 rows=[]; sampled=set(); pdfcache={}
 idx=0
 while len(rows)<N and idx<len(eds):
  ed=eds[idx]; idx+=1; eid=str(ed['id']); dt=str(ed.get('data') or '').replace('/','-')
  # normalize DD/MM/YYYY
  m=re.fullmatch(r'(\d{2})/(\d{2})/(\d{4})',str(ed.get('data') or ''))
  if m: dt=f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
  toc_url=cfg['base']+cfg['toc'].format(id=eid)
  try: ms=matters(get(s,toc_url,60,3).text)
  except: continue
  if not ms: continue
  if eid not in pdfcache: pdfcache[eid]=pdf_issue(s,cfg['base'],eid)
  ptxt,pstat,ppages,purl=pdfcache[eid]
  avail=[x for x in ms if x['id'] not in sampled]
  if len(avail)>PER_ED:
   step=len(avail)/PER_ED; choose=[avail[min(int(i*step),len(avail)-1)] for i in range(PER_ED)]
  else: choose=avail
  for x in choose:
   if len(rows)>=N: break
   pid=x['id']; u=f"{cfg['base']}/apifront/portal/edicoes/publicacoes_ver_conteudo/{pid}"
   try: txt=clean(get(s,u,60,3).text)
   except: continue
   if len(txt.strip())<30: continue
   sampled.add(pid); fn=f'{pid}_{dt}.txt'; (td/fn).write_text(txt,encoding='utf-8')
   c=cov(txt,ptxt)
   rows.append({'state':st,'publication_id':pid,'edition_id':eid,'edition_number':ed.get('numero'),'date':dt,'title':x['title'],'filename':fn,'content_url':u,'toc_url':toc_url,'pdf_url':purl,'txt_chars':len(txt),'txt_lines':len(txt.splitlines()),'pdf_status':pstat,'pdf_pages':ppages,'pdf_5gram_coverage':'' if c is None else round(c,4)})
  print(st, len(rows),'samples after edition',eid,dt,flush=True)
 # If latest endpoint wasn't enough, explicitly walk backwards by edition IDs isn't safe; fail loudly.
 fields=['state','publication_id','edition_id','edition_number','date','title','filename','content_url','toc_url','pdf_url','txt_chars','txt_lines','pdf_status','pdf_pages','pdf_5gram_coverage']
 with (sd/'manifest.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 cs=[float(r['pdf_5gram_coverage']) for r in rows if r['pdf_5gram_coverage']!='']
 summary={'state':st,'sample_count':len(rows),'unique_ids':len(sampled),'dates':dict(Counter(r['date'] for r in rows)),'publication_unit':'one individual publication/matter','unique_identifier':'numeric publication_id from issue HTML TOC','filename_rule':'{publication_id}_{YYYY-MM-DD}.txt','pdf_comparable':len(cs),'mean_pdf_5gram_coverage':round(sum(cs)/len(cs),4) if cs else None,'pdf_status_counts':dict(Counter(r['pdf_status'] for r in rows))}
 (sd/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 zp=ROOT/f'{st}_100_txt.zip'
 with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED) as z:
  for p in td.glob('*.txt'): z.write(p,p.name)
  z.write(sd/'manifest.csv','manifest.csv');z.write(sd/'summary.json','summary.json')
 return summary

def main():
 sums=[]
 for st,cfg in SITES.items():
  print('===',st,'===',flush=True); sums.append(run(st,cfg)); print(sums[-1],flush=True)
 (ROOT/'ASSESSMENT.md').write_text('\n'.join(['# AM/BA HTML sample assessment','',*sum(([f"## {s['state']}",f"- TXT count: {s['sample_count']}",f"- Unit: {s['publication_unit']}",f"- Unique identifier: {s['unique_identifier']}",f"- Filename: {s['filename_rule']}",f"- PDF-comparable: {s['pdf_comparable']}",f"- Mean 5-gram coverage vs issue PDF: {s['mean_pdf_5gram_coverage']}",''] for s in sums),[])]),encoding='utf-8')
 if any(s['sample_count']<N for s in sums): raise SystemExit('Did not reach 100 for all states; inspect artifacts/logs.')

if __name__=='__main__': main()
