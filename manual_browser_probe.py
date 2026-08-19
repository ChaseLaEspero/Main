from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

OUT = Path('manual_browser_probe_results')
OUT.mkdir(exist_ok=True)

TARGETS = {
    'AC': 'https://diario.ac.gov.br/',
    'MA': 'https://diariooficial.ma.gov.br/acervo/',
    'PE': 'https://diariooficial.cepe.com.br/diariooficialweb/#/busca-avancada?diario=MQ==&inicio=01-01-2010&fim=31-12-2010&palavra=concurso&consultar=true',
}

INTEREST = re.compile(r'api|json|xml|pdf|download|acervo|edicao|edição|publica|materia|matéria|busca|search|arquivo|diario|diário', re.I)

async def inspect(browser, state, url):
    ctx = await browser.new_context(
        locale='pt-BR',
        ignore_https_errors=True,
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36',
    )
    page = await ctx.new_page()
    page.set_default_timeout(20_000)
    result = {'state': state, 'start_url': url, 'errors': [], 'requests': [], 'responses': []}
    seen_req = set(); seen_resp = set()

    def on_request(req):
        if not INTEREST.search(req.url):
            return
        key=(req.method, req.url, req.post_data or '')
        if key in seen_req: return
        seen_req.add(key)
        result['requests'].append({'method':req.method,'url':req.url,'resource_type':req.resource_type,'post_data':req.post_data})

    async def on_response(resp):
        if not INTEREST.search(resp.url):
            return
        key=(resp.status,resp.url)
        if key in seen_resp:return
        seen_resp.add(key)
        try: headers=await resp.all_headers()
        except: headers={}
        item={'status':resp.status,'url':resp.url,'content_type':headers.get('content-type','')}
        ct=item['content_type'].lower()
        if any(x in ct for x in ('json','xml','text','javascript')):
            try:
                body=await resp.text(); item['body_length']=len(body); item['body_preview']=body[:12000]
            except Exception as exc:item['body_error']=f'{type(exc).__name__}: {exc}'
        result['responses'].append(item)

    page.on('request', on_request)
    page.on('response', on_response)
    try:
        resp=await page.goto(url,wait_until='domcontentloaded',timeout=120_000)
        result['navigation_status']=resp.status if resp else None
        await page.wait_for_timeout(10_000)
    except Exception as exc:
        result['errors'].append(f'goto: {type(exc).__name__}: {exc}')
        try: await page.evaluate('window.stop()')
        except: pass
    result['final_url']=page.url
    try: result['title']=await page.title()
    except: result['title']=''
    try:
        html=await page.content(); result['html_length']=len(html); (OUT/f'{state}_page.html').write_text(html,encoding='utf-8')
    except Exception as exc:result['errors'].append(f'content: {type(exc).__name__}: {exc}')

    try:
        result['forms']=await page.locator('form').evaluate_all("""forms => forms.map((f,fi)=>({
          fi, action:f.action||f.getAttribute('action')||'', method:f.method||'', id:f.id||'', cls:(f.className||'').toString(),
          fields:Array.from(f.querySelectorAll('input,select,textarea,button')).map((e,i)=>({i,tag:e.tagName,type:e.type||'',name:e.name||'',id:e.id||'',value:(e.value||'').toString(),text:(e.innerText||'').trim(),placeholder:e.getAttribute('placeholder')||'',options:e.tagName==='SELECT'?Array.from(e.options).map(o=>({value:o.value,text:o.text,selected:o.selected})):null}))
        }))""")
    except Exception as exc: result['errors'].append(f'forms: {type(exc).__name__}: {exc}')

    try:
        result['controls']=await page.locator('input,select,textarea,button,a').evaluate_all("""els => els.slice(0,1200).map((e,i)=>({i,tag:e.tagName,type:e.type||'',name:e.name||'',id:e.id||'',value:(e.value||'').toString(),text:(e.innerText||e.textContent||'').trim().replace(/\\s+/g,' ').slice(0,400),href:e.href||'',placeholder:e.getAttribute('placeholder')||'',options:e.tagName==='SELECT'?Array.from(e.options).map(o=>({value:o.value,text:o.text,selected:o.selected})):null}))""")
    except Exception as exc: result['errors'].append(f'controls: {type(exc).__name__}: {exc}')

    try:
        scripts=await page.locator('script[src]').evaluate_all('els=>Array.from(new Set(els.map(s=>s.src)))')
        result['scripts']=scripts
        for i,src in enumerate(scripts[:50]):
            try:
                r=await ctx.request.get(src,timeout=120_000,fail_on_status_code=False)
                text=await r.text()
                safe=re.sub(r'[^A-Za-z0-9._-]+','_',src.split('/')[-1] or f'script_{i}.js')
                (OUT/f'{state}_script_{i:02d}_{safe}.txt').write_text(text,encoding='utf-8')
                hits=[]
                for m in INTEREST.finditer(text):
                    hits.append(text[max(0,m.start()-400):min(len(text),m.end()+900)])
                    if len(hits)>=100:break
                result.setdefault('script_hits',[]).append({'url':src,'status':r.status,'length':len(text),'hits':hits})
            except Exception as exc:
                result.setdefault('script_hits',[]).append({'url':src,'error':f'{type(exc).__name__}: {exc}'})
    except Exception as exc: result['errors'].append(f'scripts: {type(exc).__name__}: {exc}')

    # State-specific interactions.
    if state == 'MA':
        try:
            selects=page.locator('select')
            n=await selects.count()
            result['ma_select_count']=n
            # choose 2010 wherever present, then first non-empty options in the other selects
            for i in range(n):
                sel=selects.nth(i)
                opts=await sel.locator('option').evaluate_all('os=>os.map(o=>({value:o.value,text:o.text}))')
                year=next((o for o in opts if '2010' in (o['text'] or '') or o['value']=='2010'),None)
                if year:
                    await sel.select_option(year['value'])
                else:
                    non=next((o for o in opts if o['value'] and o['value'] not in ('0','-1')),None)
                    if non: await sel.select_option(non['value'])
                await page.wait_for_timeout(2500)
            # click buttons likely to run search
            for label in ['Buscar','Pesquisar','Consultar','Filtrar']:
                loc=page.get_by_text(label,exact=False)
                if await loc.count():
                    try: await loc.first.click(); await page.wait_for_timeout(8000); break
                    except: pass
            result['ma_rows']=await page.locator('table tbody tr').evaluate_all("trs=>trs.map(tr=>({text:(tr.innerText||'').trim(),links:Array.from(tr.querySelectorAll('a')).map(a=>({text:(a.innerText||'').trim(),href:a.href||''}))})).slice(0,100)")
        except Exception as exc: result['errors'].append(f'MA interaction: {type(exc).__name__}: {exc}')

    if state == 'AC':
        try:
            # Attempt a 2009 month/date search using visible inputs and form submission.
            controls=page.locator('input')
            n=await controls.count()
            for i in range(n):
                el=controls.nth(i)
                ph=(await el.get_attribute('placeholder') or '').lower()
                name=(await el.get_attribute('name') or '').lower()
                typ=(await el.get_attribute('type') or '').lower()
                if any(k in ph+name for k in ('mes','mês','month')):
                    await el.fill('06/2009')
                elif 'data' in ph+name or typ=='date':
                    try: await el.fill('2009-06-22' if typ=='date' else '22/06/2009')
                    except: pass
            # Submit each form one at a time and capture resulting DOM.
            forms=page.locator('form'); fn=await forms.count(); result['ac_form_submissions']=[]
            for i in range(min(fn,10)):
                try:
                    await forms.nth(i).evaluate('(f)=>f.submit()')
                    await page.wait_for_timeout(7000)
                    result['ac_form_submissions'].append({'form':i,'url':page.url,'text':(await page.locator('body').inner_text())[:8000]})
                    await page.go_back(wait_until='domcontentloaded',timeout=60_000); await page.wait_for_timeout(2000)
                except Exception as exc: result['ac_form_submissions'].append({'form':i,'error':f'{type(exc).__name__}: {exc}'})
        except Exception as exc: result['errors'].append(f'AC interaction: {type(exc).__name__}: {exc}')

    if state == 'PE':
        try:
            result['pe_body_text']=(await page.locator('body').inner_text())[:15000]
            # Try filling date/search controls if present and click Buscar/Pesquisar.
            for selector,value in [
                ('input[placeholder*="inicial" i]','01-01-2010'),
                ('input[placeholder*="final" i]','31-12-2010'),
                ('input[placeholder*="palavra" i]','concurso'),
            ]:
                loc=page.locator(selector)
                if await loc.count():
                    try: await loc.first.fill(value)
                    except: pass
            for label in ['Buscar','Pesquisar','Consultar']:
                loc=page.get_by_text(label,exact=False)
                if await loc.count():
                    try: await loc.first.click(); await page.wait_for_timeout(15000); break
                    except: pass
            result['pe_body_text_after']=(await page.locator('body').inner_text())[:20000]
        except Exception as exc: result['errors'].append(f'PE interaction: {type(exc).__name__}: {exc}')

    (OUT/f'{state}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    await ctx.close()
    return result

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        results=[]
        for st,url in TARGETS.items():
            print('START',st,flush=True)
            results.append(await inspect(browser,st,url))
            print('DONE',st,flush=True)
        await browser.close()
    (OUT/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': asyncio.run(main())
