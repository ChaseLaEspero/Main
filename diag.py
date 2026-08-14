from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright

SITES = {
    "AM": "https://diario.imprensaoficial.am.gov.br/",
    "BA": "https://dool.egba.ba.gov.br/",
}

OUT = Path("diagnostic")
OUT.mkdir(exist_ok=True)

ENDPOINT_RE = re.compile(r"(?:https?://[^\"'\\\s]+)?/?(?:api(?:front)?|portal)/[^\"'\\\s<>]+", re.I)
KEYWORD_RE = re.compile(r"(?:edicoes_from_data|publicacoes_ver_conteudo|visualizacoes/html|download|consulta|buscar|pesquisa)", re.I)


async def inspect_site(browser, state: str, base_url: str) -> dict:
    context = await browser.new_context(locale="pt-BR", ignore_https_errors=True)
    page = await context.new_page()
    network = []

    def on_request(req):
        network.append({"kind": "request", "method": req.method, "url": req.url})

    async def on_response(resp):
        try:
            ct = (await resp.all_headers()).get("content-type", "")
        except Exception:
            ct = ""
        network.append({"kind": "response", "status": resp.status, "content_type": ct, "url": resp.url})

    page.on("request", on_request)
    page.on("response", on_response)

    result = {"state": state, "base_url": base_url, "errors": []}
    try:
        await page.goto(base_url, wait_until="domcontentloaded", timeout=120_000)
        await page.wait_for_timeout(8_000)
    except Exception as exc:
        result["errors"].append(f"goto: {type(exc).__name__}: {exc}")

    try:
        html = await page.content()
        (OUT / f"{state}_page.html").write_text(html, encoding="utf-8")
    except Exception as exc:
        html = ""
        result["errors"].append(f"content: {type(exc).__name__}: {exc}")

    try:
        result["title"] = await page.title()
        result["url"] = page.url
        result["inputs"] = await page.locator("input, select, button, a").evaluate_all(
            """els => els.map((e, i) => ({
                i,
                tag: e.tagName,
                type: e.getAttribute('type'),
                name: e.getAttribute('name'),
                id: e.id,
                cls: e.className?.toString?.() || '',
                text: (e.innerText || e.value || '').trim().slice(0, 300),
                href: e.href || '',
                placeholder: e.getAttribute('placeholder'),
                aria: e.getAttribute('aria-label')
            }))"""
        )
    except Exception as exc:
        result["errors"].append(f"dom: {type(exc).__name__}: {exc}")
        result["inputs"] = []

    scripts = []
    try:
        script_urls = await page.locator("script[src]").evaluate_all("els => els.map(e => e.src)")
        for idx, src in enumerate(dict.fromkeys(script_urls)):
            item = {"url": src}
            try:
                response = await context.request.get(src, timeout=120_000)
                item["status"] = response.status
                text = await response.text()
                item["length"] = len(text)
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", src.split("/")[-1] or f"script_{idx}.js")
                (OUT / f"{state}_{idx:02d}_{safe_name}").write_text(text, encoding="utf-8")
                endpoints = sorted(set(ENDPOINT_RE.findall(text)))
                keyword_hits = []
                for match in KEYWORD_RE.finditer(text):
                    left = max(0, match.start() - 300)
                    right = min(len(text), match.end() + 500)
                    keyword_hits.append(text[left:right])
                    if len(keyword_hits) >= 30:
                        break
                item["endpoints"] = endpoints[:500]
                item["keyword_hits"] = keyword_hits
            except Exception as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
            scripts.append(item)
    except Exception as exc:
        result["errors"].append(f"scripts: {type(exc).__name__}: {exc}")

    result["scripts"] = scripts
    result["network"] = network
    (OUT / f"{state}_network.json").write_text(json.dumps(network, ensure_ascii=False, indent=2), encoding="utf-8")
    await context.close()
    return result


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        results = []
        for state, url in SITES.items():
            results.append(await inspect_site(browser, state, url))
        await browser.close()
    (OUT / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2)[:30000])


if __name__ == "__main__":
    asyncio.run(main())
