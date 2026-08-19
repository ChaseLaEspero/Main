from __future__ import annotations

import html
import json
import re
import time
from urllib.parse import quote, unquote, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

STATES = {
    'AC': 'Acre', 'AL': 'Alagoas', 'AP': 'Amapá', 'CE': 'Ceará',
    'ES': 'Espírito Santo', 'GO': 'Goiás', 'MA': 'Maranhão', 'PA': 'Pará',
    'PB': 'Paraíba', 'PE': 'Pernambuco', 'PI': 'Piauí', 'RN': 'Rio Grande do Norte',
    'RO': 'Rondônia', 'RR': 'Roraima', 'SE': 'Sergipe', 'TO': 'Tocantins',
}

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
s = requests.Session()
s.headers.update({'User-Agent': UA, 'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8'})


def ddg(query: str, limit: int = 8):
    url = 'https://html.duckduckgo.com/html/?q=' + quote(query)
    r = s.get(url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    out = []
    for res in soup.select('.result'):
        a = res.select_one('.result__a')
        if not a:
            continue
        href = a.get('href', '')
        # DDG redirects: unwrap uddg
        try:
            q = parse_qs(urlparse(href).query)
            if 'uddg' in q:
                href = unquote(q['uddg'][0])
        except Exception:
            pass
        snippet = res.select_one('.result__snippet')
        out.append({
            'title': ' '.join(a.get_text(' ', strip=True).split()),
            'url': href,
            'snippet': ' '.join((snippet.get_text(' ', strip=True) if snippet else '').split()),
        })
        if len(out) >= limit:
            break
    return out


def main():
    all_results = {}
    for uf, name in STATES.items():
        queries = [
            f'"Diário Oficial" {name} arquivo edições site:gov.br',
            f'"Diário Oficial do Estado" {name} pesquisa edição PDF HTML',
            f'{name} imprensa oficial diário oficial acervo',
        ]
        merged = []
        seen = set()
        for q in queries:
            try:
                for item in ddg(q):
                    key = item['url']
                    if key and key not in seen:
                        seen.add(key); merged.append(item)
            except Exception as exc:
                merged.append({'title':'SEARCH_ERROR','url':'','snippet':f'{type(exc).__name__}: {exc}'})
            time.sleep(1)
        all_results[uf] = merged[:20]
        print(f'\n===== {uf} — {name} =====')
        for i, item in enumerate(all_results[uf], 1):
            print(f'{i}. {item["title"]}\n   {item["url"]}\n   {item["snippet"][:500]}')
    with open('remaining_states_search_results.json','w',encoding='utf-8') as f:
        json.dump(all_results,f,ensure_ascii=False,indent=2)

if __name__ == '__main__':
    main()
