from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

OUT=Path('manual_review_results');OUT.mkdir(exist_ok=True)
URL='https://diario.ac.gov.br/'

DATE_RE=re.compile(r'(?<!\d)(\d{2})/(\d{2})/(\d{4})(?!\d)')

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        ctx=await browser.new_context(locale='pt-BR',ignore_https_errors=True,user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36')
        page=await ctx.new_page();page.set_default_timeout(30_000)
        await page.goto(URL,wait_until='domcontentloaded',timeout=120_000)
        await page.locator('#mesano').fill('06/2009')
        form=page.locator('#mesano').locator('xpath=ancestor::form')
        await form.locator('button[type=submit]').click()
        await page.wait_for_load_state('domcontentloaded',timeout=120_000)
        await page.wait_for_timeout(5000)
        rows=await page.locator('tr, .ed-caixa, li, article, .item, .resultado').evaluate_all("""els=>els.map(e=>({text:(e.innerText||'').trim().replace(/\\s+/g,' '),links:Array.from(e.querySelectorAll('a')).map(a=>({text:(a.innerText||'').trim(),href:a.href||''}))})).filter(x=>x.text||x.links.length)""")
        all_links=await page.locator('a[href]').evaluate_all("as=>as.map(a=>({text:(a.innerText||'').trim(),href:a.href||''}))")
        candidates=[]
        for row in rows:
            m=DATE_RE.search(row.get('text',''))
            if not m:continue
            dt=f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
            for a in row.get('links',[]):
                if 'download.php?arquivo=' in a.get('href',''):
                    candidates.append({'date':dt,'text':row.get('text',''),'download_url':a['href']})
        if not candidates:
            # fallback: pair each download link with nearest date in document order through JS evaluation
            candidates=await page.locator('a[href*="download.php?arquivo="]').evaluate_all("""as=>as.map(a=>{let e=a;for(let i=0;i<8&&e;i++,e=e.parentElement){const t=(e.innerText||'').replace(/\\s+/g,' ');const m=t.match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})/);if(m)return {date:`${m[3]}-${m[2]}-${m[1]}`,text:t,download_url:a.href};}return {date:null,text:(a.parentElement?.innerText||''),download_url:a.href};})""")
        candidates=[x for x in candidates if x.get('date')]
        candidates.sort(key=lambda x:(x['date'],x['download_url']))
        earliest=candidates[0] if candidates else None
        verification=None
        if earliest:
            r=await ctx.request.get(earliest['download_url'],timeout=180_000,fail_on_status_code=False,headers={'Range':'bytes=0-4095'})
            body=await r.body();verification={'status':r.status,'content_type':r.headers.get('content-type',''),'content_length':r.headers.get('content-length'),'is_pdf':body.startswith(b'%PDF-'),'bytes_received':len(body)}
        result={'state':'AC','main_url':URL,'search_method':'POST mesano=06/2009','earliest_online_issue':earliest,'all_june_2009_issues':candidates,'earliest_pdf_verification':verification,'covers_2010_2021':bool(earliest and earliest['date']<='2010-01-01')}
        (OUT/'AC.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        await browser.close()

if __name__=='__main__':asyncio.run(main())
