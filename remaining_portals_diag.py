from __future__ import annotations

# Diagnostic run trigger: 2026-08-19
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

OUT = Path("remaining_portals_diag")
OUT.mkdir(exist_ok=True)

SITES = {
    "AC": "https://diario.ac.gov.br/",
    "AL": "https://diario.imprensaoficial.al.gov.br/",
    "AP": "https://diofe.portal.ap.gov.br/",
    "CE": "https://www.ce.gov.br/diario-oficial/",
    "DF": "https://dodf.df.gov.br/",
    "ES": "https://ioes.dio.es.gov.br/portal/visualizacoes/diario_oficial",
    "GO": "https://diariooficial.abc.go.gov.br/",
    "MA": "https://diariooficial.ma.gov.br/",
    "PA": "https://www.ioepa.com.br/",
    "PB": "https://auniao.pb.gov.br/servicos/doe/",
    "PE": "https://diariooficial.cepe.com.br/diariooficialweb/",
    "PI": "https://www.diario.pi.gov.br/doe/",
    "RN": "https://www.diariooficial.rn.gov.br/dei/dorn3/",
    "RO": "https://diof.ro.gov.br/",
    "RR": "https://www.imprensaoficial.rr.gov.br/",
    "SC": "https://portal.doe.sea.sc.gov.br/",
    "SE": "https://iose.se.gov.br/diario-oficial",
    "TO": "https://diariooficial.to.gov.br/",
}

INTEREST = re.compile(
    r"api|json|xml|edicao|edição|diario|diário|publica|materia|matéria|"
    r"consulta|pesquisa|busca|download|arquivo|acervo|html|pdf",
    re.I,
)

COMMON_PATHS = [
    "apifront/portal/edicoes/ultimas_edicoes.json?subtheme=false",
    "apifront/portal/edicoes/edicoes_from_data/2010-01-05.json",
    "apifront/portal/edicoes/edicoes_from_data/2021-12-31.json",
]


async def inspect(browser, state: str, start_url: str) -> dict:
    context = await browser.new_context(
        locale="pt-BR",
        ignore_https_errors=True,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()
    page.set_default_timeout(15_000)
    result: dict = {
        "state": state,
        "start_url": start_url,
        "errors": [],
        "network": [],
        "common_endpoint_tests": [],
    }
    seen_network = set()

    async def on_response(resp):
        url = resp.url
        if not INTEREST.search(url):
            return
        key = (resp.status, url)
        if key in seen_network:
            return
        seen_network.add(key)
        try:
            headers = await resp.all_headers()
        except Exception:
            headers = {}
        item = {
            "status": resp.status,
            "url": url,
            "content_type": headers.get("content-type", ""),
        }
        ct = item["content_type"].lower()
        if ("json" in ct or "xml" in ct or "text" in ct) and len(result["network"]) < 250:
            try:
                body = await resp.text()
                item["body_preview"] = body[:4000]
                item["body_length"] = len(body)
            except Exception as exc:
                item["body_error"] = f"{type(exc).__name__}: {exc}"
        result["network"].append(item)

    page.on("response", on_response)

    try:
        response = await page.goto(start_url, wait_until="domcontentloaded", timeout=45_000)
        result["navigation_status"] = response.status if response else None
        await page.wait_for_timeout(6000)
    except Exception as exc:
        result["errors"].append(f"goto: {type(exc).__name__}: {exc}")
        try:
            await page.evaluate("window.stop()")
        except Exception:
            pass

    try:
        result["final_url"] = page.url
        result["title"] = await page.title()
        html = await page.content()
        (OUT / f"{state}_page.html").write_text(html, encoding="utf-8")
        result["html_length"] = len(html)
    except Exception as exc:
        result["errors"].append(f"page content: {type(exc).__name__}: {exc}")

    try:
        result["links"] = await page.locator("a").evaluate_all(
            """els => els.slice(0, 600).map(a => ({
                text: (a.innerText || a.textContent || '').trim().replace(/\\s+/g,' ').slice(0,300),
                href: a.href || a.getAttribute('href') || '',
                id: a.id || '',
                cls: (a.className || '').toString().slice(0,200)
            }))"""
        )
    except Exception as exc:
        result["errors"].append(f"links: {type(exc).__name__}: {exc}")
        result["links"] = []

    try:
        result["forms"] = await page.locator("form").evaluate_all(
            """forms => forms.map(f => ({
                action: f.action || f.getAttribute('action') || '',
                method: f.method || f.getAttribute('method') || '',
                id: f.id || '',
                cls: (f.className || '').toString(),
                fields: Array.from(f.querySelectorAll('input,select,button')).map(e => ({
                    tag:e.tagName, type:e.type || '', name:e.name || '', id:e.id || '',
                    value:(e.value || '').toString().slice(0,300),
                    text:(e.innerText || '').trim().slice(0,300),
                    placeholder:e.getAttribute('placeholder') || ''
                }))
            }))"""
        )
    except Exception as exc:
        result["errors"].append(f"forms: {type(exc).__name__}: {exc}")
        result["forms"] = []

    try:
        result["scripts"] = await page.locator("script[src]").evaluate_all(
            "els => Array.from(new Set(els.map(s => s.src)))"
        )
    except Exception as exc:
        result["errors"].append(f"scripts: {type(exc).__name__}: {exc}")
        result["scripts"] = []

    origins = []
    for candidate in [page.url, start_url]:
        p = urlparse(candidate)
        if p.scheme and p.netloc:
            origin = f"{p.scheme}://{p.netloc}/"
            if origin not in origins:
                origins.append(origin)
    for origin in origins:
        for path in COMMON_PATHS:
            url = urljoin(origin, path)
            try:
                r = await context.request.get(url, timeout=20_000, fail_on_status_code=False)
                text = await r.text()
                result["common_endpoint_tests"].append({
                    "url": url,
                    "status": r.status,
                    "content_type": r.headers.get("content-type", ""),
                    "length": len(text),
                    "preview": text[:1200],
                })
            except Exception as exc:
                result["common_endpoint_tests"].append({
                    "url": url,
                    "error": f"{type(exc).__name__}: {exc}",
                })

    await context.close()
    (OUT / f"{state}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        sem = asyncio.Semaphore(3)

        async def one(state, url):
            async with sem:
                print(f"START {state} {url}", flush=True)
                try:
                    res = await inspect(browser, state, url)
                    print(
                        f"DONE {state}: {res.get('navigation_status')} "
                        f"{res.get('final_url')} links={len(res.get('links', []))} "
                        f"network={len(res.get('network', []))}",
                        flush=True,
                    )
                    return res
                except Exception as exc:
                    print(f"FAILED {state}: {type(exc).__name__}: {exc}", flush=True)
                    return {"state": state, "start_url": url, "fatal": f"{type(exc).__name__}: {exc}"}

        results = await asyncio.gather(*(one(s, u) for s, u in SITES.items()))
        await browser.close()

    (OUT / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
