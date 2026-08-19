from __future__ import annotations

# Trigger compact report generation: 2026-08-19
import json
from pathlib import Path

ROOT = Path('remaining_portals_diag')
OUT = ROOT / 'compact.json'

KEYWORDS = (
    'api', 'json', 'xml', 'html', 'pdf', 'download', 'edicao', 'edição',
    'publica', 'materia', 'matéria', 'arquivo', 'acervo', 'consulta',
    'pesquisa', 'busca', 'diario', 'diário', 'repositorio', 'repositório'
)


def interesting(text: str) -> bool:
    low = (text or '').lower()
    return any(k in low for k in KEYWORDS)


def compact_one(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding='utf-8'))
    links = []
    seen = set()
    for x in obj.get('links', []):
        text = str(x.get('text') or '')
        href = str(x.get('href') or '')
        if interesting(text + ' ' + href):
            key = (text, href)
            if key not in seen:
                seen.add(key)
                links.append({'text': text[:180], 'href': href})
        if len(links) >= 80:
            break

    network = []
    seen = set()
    for x in obj.get('network', []):
        url = str(x.get('url') or '')
        ct = str(x.get('content_type') or '')
        if interesting(url) or any(t in ct.lower() for t in ('json','xml','pdf')):
            key = (x.get('status'), url)
            if key not in seen:
                seen.add(key)
                network.append({
                    'status': x.get('status'),
                    'url': url,
                    'content_type': ct,
                    'body_length': x.get('body_length'),
                    'body_preview': str(x.get('body_preview') or '')[:500],
                })
        if len(network) >= 100:
            break

    tests = []
    for x in obj.get('common_endpoint_tests', []):
        tests.append({
            'url': x.get('url'), 'status': x.get('status'),
            'content_type': x.get('content_type'), 'length': x.get('length'),
            'preview': str(x.get('preview') or '')[:300], 'error': x.get('error')
        })

    forms = []
    for f in obj.get('forms', [])[:20]:
        forms.append({
            'action': f.get('action'), 'method': f.get('method'),
            'id': f.get('id'), 'fields': f.get('fields', [])[:25]
        })

    return {
        'state': obj.get('state'),
        'start_url': obj.get('start_url'),
        'final_url': obj.get('final_url'),
        'navigation_status': obj.get('navigation_status'),
        'title': obj.get('title'),
        'errors': obj.get('errors'),
        'html_length': obj.get('html_length'),
        'links': links,
        'forms': forms,
        'scripts': obj.get('scripts', [])[:30],
        'network': network,
        'common_endpoint_tests': tests,
    }


def main() -> None:
    rows = []
    for path in sorted(ROOT.glob('??.json')):
        rows.append(compact_one(path))
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'wrote {OUT} with {len(rows)} states')


if __name__ == '__main__':
    main()
