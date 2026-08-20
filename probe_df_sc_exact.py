from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from playwright.async_api import async_playwright

OUT = Path('df_sc_exact_results')
OUT.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139.0.0.0 Safari/537.36'


def safe_text(r: requests.Response, limit=200000):
    try:
        return r.text[:limit]
    except Exception:
        return ''


def request_probe(url: str) -> dict:
    s = requests.Session(); s.trust_env = False; s.headers.update({'User-Agent': UA, 'Accept': '*/*'})
    try:
        r = s.get(url, timeout=60, verify=False, allow_redirects=True)
        body = r.content[:4096]
        return {'url': url, 'final_url': r.url, 'status': r.status_code, 'content_type': r.headers.get('content-type',''), 'content_length': r.headers.get('content-length'), 'is_pdf': body.startswith(b'%PDF-'), 'preview': safe_text(r, 1200) if 'text' in r.headers.get('content-type','') or 'json' in r.headers.get('content-type','') else ''}
    except Exception as e:
        return {'url': url, 'error': f'{type(e).__name__}: {e}'}


async def browser_probe(page, url: str, wait_ms=7000):
    rec = {'start_url': url, 'requests': [], 'responses': [], 'errors': []}
    seen_req=set(); seen_resp=set()
    async def on_req(req):
        u=req.url
        if u not in seen_req and any(k in u.lower() for k in ['api','diario','jornal','mater','public','arquivo','repositorio','sinj','dodf']):
            seen_req.add(u); rec['requests'].append({'method':req.method,'url':u,'resource_type':req.resource_type,'post_data':req.post_data[:2000] if req.post_data else None})
    async def on_resp(resp):
        u=resp.url
        if u not in seen_resp and any(k in u.lower() for k in ['api','diario','jornal','mater','public','arquivo','repositorio','sinj','dodf']):
            seen_resp.add(u)
            try: h=await resp.all_headers()
            except: h={}
            item={'status':resp.status,'url':u,'content_type':h.get('content-type','')}
            if ('json' in item['content_type'].lower() or 'javascript' in item['content_type'].lower() or 'text' in item['content_type'].lower()) and len(rec['responses'])<250:
                try:
                    txt=await resp.text(); item['body_preview']=txt[:5000]; item['body_length']=len(txt)
                except: pass
            rec['responses'].append(item)
    page.on('request', on_req); page.on('response', on_resp)
    try:
        r=await page.goto(url,wait_until='domcontentloaded',timeout=120000); rec['nav_status']=r.status if r else None
        await page.wait_for_timeout(wait_ms)
    except Exception as e:
        rec['errors'].append(f'goto: {type(e).__name__}: {e}')
    rec['final_url']=page.url
    try: rec['title']=await page.title()
    except: rec['title']=''
    try:
        rec['html']=await page.content()
        rec['html_length']=len(rec['html'])
    except Exception as e:
        rec['errors'].append(f'content: {e}'); rec['html']=''
    try:
        rec['scripts']=await page.locator('script[src]').evaluate_all("els=>Array.from(new Set(els.map(x=>x.src)))")
        rec['links']=await page.locator('a[href]').evaluate_all("els=>els.slice(0,800).map(a=>({text:(a.innerText||a.textContent||'').trim().replace(/\\s+/g,' ').slice(0,250),href:a.href}))")
        rec['controls']=await page.locator('input,select,button').evaluate_all("els=>els.slice(0,500).map(e=>({tag:e.tagName,id:e.id||'',name:e.name||'',type:e.type||'',text:(e.innerText||'').trim().slice(0,200),value:(e.value||'').toString().slice(0,200),placeholder:e.getAttribute('placeholder')||''}))")
    except Exception as e: rec['errors'].append(f'dom: {e}')
    return rec


async def fetch_scripts(context, scripts):
    rows=[]
    endpoint_strings=set()
    for u in scripts[:100]:
        try:
            r=await context.request.get(u,timeout=60000,fail_on_status_code=False)
            txt=await r.text()
            if len(txt)>8_000_000: txt=txt[:8_000_000]
            matches=[]
            for pat in [r'[^"\'`\s]{0,120}(?:/apis?/|api/)[^"\'`\s]{0,220}', r'[^"\'`\s]{0,120}(?:materia|matéria|jornal|diario|diário|publicacao|publicação)[^"\'`\s]{0,220}']:
                for m in re.findall(pat,txt,re.I):
                    if len(m)<400: endpoint_strings.add(m)
            rows.append({'url':u,'status':r.status,'length':len(txt),'matches':list(endpoint_strings)[-100:]})
        except Exception as e: rows.append({'url':u,'error':f'{type(e).__name__}: {e}'})
    return rows, sorted(endpoint_strings)


async def probe_sc(browser):
    ctx=await browser.new_context(ignore_https_errors=True,locale='pt-BR',user_agent=UA)
    page=await ctx.new_page()
    rec=await browser_probe(page,'https://portal.doe.sea.sc.gov.br/',7000)
    script_rows, strings=await fetch_scripts(ctx,rec.get('scripts',[]))
    rec['script_analysis']=script_rows; rec['script_strings']=strings

    base='https://portal.doe.sea.sc.gov.br/'
    tests=[]
    candidates=[
        'apis/jornal/264','apis/jornal/266','apis/jornal/?cdJornal=266','apis/jornal/266/materias','apis/jornal/materias/266',
        'apis/materia/?cdJornal=266','apis/materia?cdJornal=266','apis/materias/?cdJornal=266','apis/materias?cdJornal=266',
        'apis/materia/jornal/266','apis/materias/jornal/266','apis/publicacao/?cdJornal=266','apis/publicacoes/?cdJornal=266',
        'apis/busca-materia/?cdJornal=266','apis/busca-materias/?cdJornal=266',
    ]
    for path in candidates:
        u=urljoin(base,path)
        try:
            r=await ctx.request.get(u,timeout=30000,fail_on_status_code=False); txt=await r.text()
            if r.status!=404 or len(txt)>1000:
                tests.append({'url':u,'status':r.status,'content_type':r.headers.get('content-type',''),'length':len(txt),'preview':txt[:5000]})
        except Exception as e: tests.append({'url':u,'error':f'{type(e).__name__}: {e}'})
    rec['candidate_api_tests']=tests

    # Verify exact current issue boundary + direct PDF paths.
    issue_urls=[
      base+'apis/jornal/?page=1&perPage=100&dtStart=1900-01-01%2000:00:00&dtEnd=2011-10-02%2023:59:59',
      base+'apis/jornal/?page=1&perPage=100&dtStart=2011-10-03%2000:00:00&dtEnd=2011-10-04%2023:59:59',
      base+'repositorio/2011/20111003/Jornal/264.pdf',
      base+'repositorio/2011/20111004/Jornal/266.pdf',
    ]
    rec['boundary_http_tests']=[]
    for u in issue_urls:
        try:
            r=await ctx.request.get(u,timeout=60000,fail_on_status_code=False); body=await r.body(); ct=r.headers.get('content-type','')
            rec['boundary_http_tests'].append({'url':u,'status':r.status,'content_type':ct,'length':len(body),'is_pdf':body.startswith(b'%PDF-'),'preview':body[:2500].decode('utf-8','replace') if ('json' in ct or 'text' in ct) else ''})
        except Exception as e: rec['boundary_http_tests'].append({'url':u,'error':f'{type(e).__name__}: {e}'})
    await ctx.close()
    (OUT/'SC_exact.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding='utf-8')
    return rec


async def probe_df(browser):
    ctx=await browser.new_context(ignore_https_errors=True,locale='pt-BR',user_agent=UA)
    page=await ctx.new_page()
    sinj=await browser_probe(page,'https://www.sinj.df.gov.br/sinj/',5000)
    scripts, strings=await fetch_scripts(ctx,sinj.get('scripts',[]))
    sinj['script_analysis']=scripts; sinj['script_strings']=strings

    # Click the official diary-directory control to expose its network route if possible.
    try:
        loc=page.get_by_text('Navegar por Diretórios',exact=False)
        if await loc.count():
            await loc.first.click(); await page.wait_for_timeout(5000)
            sinj['after_directory_click_html']=(await page.content())[:500000]
            sinj['after_directory_controls']=await page.locator('input,select,button,a[href]').evaluate_all("els=>els.slice(0,1000).map(e=>({tag:e.tagName,text:(e.innerText||e.textContent||'').trim().replace(/\\s+/g,' ').slice(0,250),id:e.id||'',name:e.name||'',href:e.href||'',value:(e.value||'').toString().slice(0,200)}))")
    except Exception as e: sinj['directory_click_error']=f'{type(e).__name__}: {e}'

    # Current DODF portal network/source.
    p2=await ctx.new_page(); dodf=await browser_probe(p2,'https://www.dodf.df.gov.br/',10000)
    dscripts,dstrings=await fetch_scripts(ctx,dodf.get('scripts',[]))
    dodf['script_analysis']=dscripts; dodf['script_strings']=dstrings

    # Concrete official SINJ pages used to validate dates/text rendering.
    urls=[
      'https://www.sinj.df.gov.br/sinj/Tutorial',
      'https://www.sinj.df.gov.br/sinj/DetalhesDeNorma.aspx?id_norma=620e58388fb44ab1ae81d3564e7e519a',
      'https://www.sinj.df.gov.br/sinj/Norma/8/Decreto_1_09_05_1960.html',
      'https://www.sinj.df.gov.br/sinj/TextoArquivoDiario.aspx?id_file=e0c614e3-0331-376d-8a6d-fbd8723c831d',
    ]
    http=[]
    for u in urls:
        try:
            r=await ctx.request.get(u,timeout=60000,fail_on_status_code=False); txt=await r.text()
            http.append({'url':u,'status':r.status,'content_type':r.headers.get('content-type',''),'length':len(txt),'preview':txt[:8000]})
        except Exception as e:http.append({'url':u,'error':f'{type(e).__name__}: {e}'})

    res={'SINJ':sinj,'DODF_current':dodf,'http_tests':http}
    await ctx.close()
    (OUT/'DF_exact.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
    return res


async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        df,sc=await asyncio.gather(probe_df(browser),probe_sc(browser))
        await browser.close()
    summary={
      'DF': {'sinj_final':df['SINJ'].get('final_url'),'sinj_errors':df['SINJ'].get('errors'),'dodf_final':df['DODF_current'].get('final_url'),'dodf_errors':df['DODF_current'].get('errors'),'sinj_script_strings':df['SINJ'].get('script_strings',[])[:200],'dodf_script_strings':df['DODF_current'].get('script_strings',[])[:200]},
      'SC': {'final_url':sc.get('final_url'),'errors':sc.get('errors'),'script_strings':sc.get('script_strings',[])[:300],'candidate_api_tests':sc.get('candidate_api_tests'),'boundary_http_tests':sc.get('boundary_http_tests')}
    }
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2)[:30000])

if __name__=='__main__': asyncio.run(main())
