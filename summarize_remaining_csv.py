from __future__ import annotations

# Trigger: 2026-08-19
import csv
import json
from pathlib import Path

ROOT = Path('remaining_portals_diag')
OUT = ROOT / 'compact.csv'

KEYWORDS = ('api','json','xml','html','pdf','download','edicao','edição','publica','materia','matéria','arquivo','acervo','consulta','pesquisa','busca','diario','diário','repositorio','repositório')

def good(s: str) -> bool:
    x = (s or '').lower()
    return any(k in x for k in KEYWORDS)

rows=[]
for p in sorted(ROOT.glob('??.json')):
    o=json.loads(p.read_text(encoding='utf-8'))
    links=[]
    for x in o.get('links',[]):
        text=str(x.get('text') or '').replace('\n',' ').strip()
        href=str(x.get('href') or '')
        if good(text+' '+href): links.append((text+' -> '+href)[:350])
        if len(links)>=20: break
    nets=[]
    for x in o.get('network',[]):
        u=str(x.get('url') or '')
        ct=str(x.get('content_type') or '')
        if good(u) or any(k in ct.lower() for k in ('json','xml','pdf')):
            nets.append(f"{x.get('status')} {ct} {u}"[:400])
        if len(nets)>=30: break
    tests=[]
    for x in o.get('common_endpoint_tests',[]):
        if x.get('status') not in (404, None) or (x.get('length') or 0)>500:
            tests.append(f"{x.get('status')} {x.get('content_type')} {x.get('url')} len={x.get('length')}")
    rows.append({
        'state':o.get('state'),'start_url':o.get('start_url'),'final_url':o.get('final_url'),
        'navigation_status':o.get('navigation_status'),'title':o.get('title'),
        'errors':' | '.join(o.get('errors') or []),
        'links':' || '.join(links),'network':' || '.join(nets),'endpoint_tests':' || '.join(tests),
        'scripts':' || '.join(o.get('scripts') or [])
    })

fields=['state','start_url','final_url','navigation_status','title','errors','links','network','endpoint_tests','scripts']
with OUT.open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
print('wrote',OUT,len(rows))
