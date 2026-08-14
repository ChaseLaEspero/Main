from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

PAGES = {
    "AM": "https://diario.imprensaoficial.am.gov.br/portal/visualizacoes/html/18190/",
    "BA": "https://www.doe.ba.gov.br/ver-html/22380/",
}
OUT = Path("viewdiag")
OUT.mkdir(exist_ok=True)

async def inspect(browser, state, url):
    ctx = await browser.new_context(locale="pt-BR", ignore_https_errors=True)
    page = await ctx.new_page()
    net=[]
    page.on("request", lambda req: net.append({"kind":"req","method":req.method,"url":req.url}))
    async def onresp(resp):
        try: ct=(await resp.all_headers()).get("content-type","")
        except: ct=""
        net.append({"kind":"resp","status":resp.status,"ct":ct,"url":resp.url})
    page.on("response", onresp)
    errors=[]
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(10000)
    except Exception as e: errors.append(f"goto {type(e).__name__}: {e}")
    try:
        html=await page.content(); (OUT/f"{state}.html").write_text(html,encoding="utf-8")
    except Exception as e: html=""; errors.append(f"content {type(e).__name__}: {e}")
    scripts=[]
    try:
        urls=await page.locator("script[src]").evaluate_all("els=>els.map(e=>e.src)")
        for i,src in enumerate(dict.fromkeys(urls)):
            rec={"url":src}
            try:
                r=await ctx.request.get(src,timeout=60000); txt=await r.text(); rec["status"]=r.status; rec["len"]=len(txt)
                name=re.sub(r"[^A-Za-z0-9._-]+","_",src.split('/')[-1] or f"script{i}.js")
                (OUT/f"{state}_{i:02d}_{name}").write_text(txt,encoding="utf-8")
                hits=[]
                for m in re.finditer(r"(?:publicacoes|conteudo|materia|html|categoria|edicao|pagina)",txt,re.I):
                    hits.append(txt[max(0,m.start()-400):min(len(txt),m.end()+800)])
                    if len(hits)>=80: break
                rec["hits"]=hits
            except Exception as e: rec["error"]=f"{type(e).__name__}: {e}"
            scripts.append(rec)
    except Exception as e: errors.append(f"scripts {type(e).__name__}: {e}")
    try:
        dom=await page.locator("a,button,[data-id],[data-publicacao],[data-publicacao-id],[onclick]").evaluate_all("""els=>els.map((e,i)=>({i,tag:e.tagName,text:(e.innerText||'').trim().slice(0,500),href:e.href||'',onclick:e.getAttribute('onclick'),data:{...e.dataset},cls:e.className?.toString?.()||''})).filter(x=>x.text||x.href||x.onclick||Object.keys(x.data).length)""")
    except Exception as e: dom=[]; errors.append(f"dom {type(e).__name__}: {e}")
    result={"state":state,"input":url,"url":page.url,"title":await page.title(),"errors":errors,"network":net,"scripts":scripts,"dom":dom}
    (OUT/f"{state}_network.json").write_text(json.dumps(net,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/f"{state}_dom.json").write_text(json.dumps(dom,ensure_ascii=False,indent=2),encoding="utf-8")
    await ctx.close()
    return result

async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True)
        res=[]
        for st,u in PAGES.items(): res.append(await inspect(b,st,u))
        await b.close()
    (OUT/'summary.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
    for r in res:
        print('\nSTATE',r['state'],'URL',r['url'],'errors',r['errors'])
        print('NETWORK')
        for n in r['network']:
            u=n['url']
            if '/api' in u.lower() or 'public' in u.lower() or 'conte' in u.lower(): print(n)
        print('DOM first',r['dom'][:30])

if __name__=='__main__': asyncio.run(main())
