from __future__ import annotations

import json
from pathlib import Path

ROOT = Path('boundary_probe')
OUT = ROOT / 'compact_summary.json'


def slim_response(x):
    if not isinstance(x, dict):
        return x
    out = {k: x.get(k) for k in ('status','url','content_type','length','error') if k in x}
    j = x.get('json')
    if isinstance(j, dict):
        out['json_keys'] = list(j)[:30]
        # common compact fields
        for key in ('status','error','total','count','recordsTotal','recordsFiltered','data','editions','records'):
            if key in j:
                v=j[key]
                if isinstance(v,list): out[f'{key}_len']=len(v); out[f'{key}_first']=v[:2]; out[f'{key}_last']=v[-2:]
                elif isinstance(v,dict):
                    out[f'{key}_keys']=list(v)[:30]
                    if 'meta' in v: out[f'{key}_meta']=v.get('meta')
                    if isinstance(v.get('data'),list):
                        out[f'{key}_data_len']=len(v['data']);out[f'{key}_data_first']=v['data'][:2];out[f'{key}_data_last']=v['data'][-2:]
                else: out[key]=v
        # preserve small JSON completely
        raw=json.dumps(j,ensure_ascii=False)
        if len(raw)<15000: out['json']=j
    prev=x.get('preview')
    if prev and not j: out['preview']=str(prev)[:2000]
    return out

res={}
for st in ['AL','PE','PI','SC']:
    p=ROOT/f'{st}.json'
    if not p.exists():continue
    obj=json.loads(p.read_text(encoding='utf-8'))
    res[st]={k:slim_response(v) for k,v in obj.items()}
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print('wrote',OUT)
