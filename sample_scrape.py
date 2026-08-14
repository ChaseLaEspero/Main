from __future__ import annotations

import csv
import html as htmllib
import json
import re
import shutil
import time
import unicodedata
import zipfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import requests
from bs4 import BeautifulSoup

ROOT = Path('samples')
ROOT.mkdir(exist_ok=True)
N_PER_STATE = 100
MAX_PER_EDITION = 5
START = date(2010, 1, 1)
END = date(2021, 12, 31)

SITES = {
    'AM': {
        'base': 'https://diario.imprensaoficial.am.gov.br',
        'edition_toc': '/portal/visualizacoes/view_html_diario/{edition_id}',
    },
    'BA': {
        'base': 'https://www.doe.ba.gov.br',
        'edition_toc': '/html/{edition_id}.html',
    },
}

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36'


def norm(s: str) -> str:
    s = htmllib.unescape(s or '')
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = re.sub(r'[^0-9a-z\s]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def clean_html_to_text(raw: str) -> str:
    soup = BeautifulSoup(raw, 'html.parser')
    for tag in soup(['script', 'style', 'noscript', 'svg']):
        tag.decompose()
    # Keep table structure readable before stripping markup.
    for tr in soup.find_all('tr'):
        cells = [c.get_text(' ', strip=True) for c in tr.find_all(['th', 'td'])]
        if cells:
            tr.replace_with('\t'.join(cells) + '\n')
    text = soup.get_text('\n')
    lines = []
    blank = False
    for ln in text.splitlines():
        ln = re.sub(r'[ \t\xa0]+', ' ', ln).strip()
        if ln:
            lines.append(ln)
            blank = False
        elif lines and not blank:
            lines.append('')
            blank = True
    return '\n'.join(lines).strip() + '\n'


def matter_ids_from_toc(raw: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(raw, 'html.parser')
    found: list[dict[str, str]] = []
    seen = set()
    for a in soup.select('a.linkMateria, a[identificador], a[data-materia-id]'):
        mid = a.get('identificador') or a.get('data-materia-id') or a.get('data-id')
        if not mid:
            continue
        mid = str(mid).strip()
        if not mid.isdigit() or mid in seen:
            continue
        seen.add(mid)
        found.append({
            'publication_id': mid,
            'title': a.get_text(' ', strip=True),
        })
    return found


def choose_principal(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    # Prefer a non-supplement main edition. The site schemas differ slightly.
    for it in items:
        sup = it.get('suplemento')
        tipo = str(it.get('tipo_edicao_nome') or '').casefold()
        if sup in ('', None, 0, '0', False) and 'extra' not in tipo and 'suplement' not in tipo:
            return it
    return sorted(items, key=lambda x: int(x.get('id') or 10**18))[0]


def target_dates() -> list[date]:
    # 4 anchors per year, enough to test the entire 2010-2021 range and
    # prevent all 100 samples from coming from one recent issue.
    out = []
    for year in range(2010, 2022):
        for month, day in [(2, 15), (5, 15), (8, 15), (11, 15)]:
            out.append(date(year, month, day))
    return out


def get_with_retry(s: requests.Session, url: str, *, timeout=60, attempts=4) -> requests.Response:
    last = None
    for i in range(attempts):
        try:
            r = s.get(url, timeout=timeout)
            if r.status_code in {429, 500, 502, 503, 504}:
                last = RuntimeError(f'HTTP {r.status_code}')
                time.sleep(1.5 * (i + 1))
                continue
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'GET failed: {url}: {last}')


def edition_for_near_date(s: requests.Session, cfg: dict[str, str], target: date) -> tuple[date, dict[str, Any]] | None:
    # Search target date +/- 5 days, prioritizing nearby weekdays.
    offsets = [0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5]
    for off in offsets:
        d = target + timedelta(days=off)
        if d < START or d > END:
            continue
        url = f"{cfg['base']}/apifront/portal/edicoes/edicoes_from_data/{d.isoformat()}.json"
        try:
            r = get_with_retry(s, url, timeout=45, attempts=2)
            obj = r.json()
            items = obj.get('itens') or []
            principal = choose_principal(items)
            if principal and principal.get('id'):
                return d, principal
        except Exception:
            continue
    return None


def pdf_text_and_status(s: requests.Session, base: str, edition_id: str, pdf_dir: Path) -> tuple[str, str, int, str]:
    url = f'{base}/portal/edicoes/download/{edition_id}'
    try:
        r = get_with_retry(s, url, timeout=120, attempts=2)
        data = r.content
        if not data.startswith(b'%PDF-'):
            return '', 'not_pdf_or_auth_required', 0, url
        path = pdf_dir / f'{edition_id}.pdf'
        path.write_bytes(data)
        doc = fitz.open(stream=data, filetype='pdf')
        text = '\n'.join(page.get_text('text') for page in doc)
        pages = doc.page_count
        return text, 'ok' if text.strip() else 'pdf_no_text_layer', pages, url
    except Exception as exc:
        return '', f'error:{type(exc).__name__}', 0, url


def shingle_coverage(publication_text: str, issue_pdf_text: str, n: int = 5) -> float | None:
    a = norm(publication_text).split()
    b = norm(issue_pdf_text)
    if len(a) < n or not b:
        return None
    # Cap to 200 evenly spaced shingles for speed and robustness.
    starts = list(range(0, len(a) - n + 1))
    if len(starts) > 200:
        step = len(starts) / 200
        starts = [int(i * step) for i in range(200)]
    shingles = [' '.join(a[i:i+n]) for i in starts]
    if not shingles:
        return None
    return sum(1 for sh in shingles if sh in b) / len(shingles)


def run_state(state: str, cfg: dict[str, str]) -> dict[str, Any]:
    state_dir = ROOT / state
    txt_dir = state_dir / 'txt'
    pdf_dir = state_dir / 'pdf_reference'
    txt_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept': '*/*', 'Referer': cfg['base'] + '/'})
    s.trust_env = True

    samples: list[dict[str, Any]] = []
    edition_cache: dict[str, dict[str, Any]] = {}
    sampled_ids = set()
    coverage_tests = []

    anchors = target_dates()
    # If needed, add monthly anchors across the period to reach 100.
    extra = []
    for y in range(2010, 2022):
        for m in range(1, 13):
            extra.append(date(y, m, 10))
    candidates = anchors + [d for d in extra if d not in anchors]

    for target in candidates:
        if len(samples) >= N_PER_STATE:
            break
        found = edition_for_near_date(s, cfg, target)
        if not found:
            coverage_tests.append({'target_date': target.isoformat(), 'edition_found': False})
            continue
        actual_date, edition = found
        eid = str(edition['id'])
        toc_url = cfg['base'] + cfg['edition_toc'].format(edition_id=eid)
        try:
            toc_resp = get_with_retry(s, toc_url, timeout=60, attempts=3)
            toc_raw = toc_resp.text
            matters = matter_ids_from_toc(toc_raw)
        except Exception as exc:
            coverage_tests.append({
                'target_date': target.isoformat(), 'actual_date': actual_date.isoformat(),
                'edition_id': eid, 'edition_found': True, 'html_toc': False,
                'error': f'{type(exc).__name__}: {exc}'
            })
            continue

        coverage_tests.append({
            'target_date': target.isoformat(), 'actual_date': actual_date.isoformat(),
            'edition_id': eid, 'edition_number': edition.get('numero'), 'edition_found': True,
            'html_toc': bool(matters), 'matter_count': len(matters), 'toc_url': toc_url,
        })
        if not matters:
            continue

        if eid not in edition_cache:
            pdf_text, pdf_status, pdf_pages, pdf_url = pdf_text_and_status(s, cfg['base'], eid, pdf_dir)
            edition_cache[eid] = {
                'pdf_text': pdf_text, 'pdf_status': pdf_status,
                'pdf_pages': pdf_pages, 'pdf_url': pdf_url,
            }
        pdfinfo = edition_cache[eid]

        # Spread the sample through the TOC instead of always taking the first five.
        available = [m for m in matters if m['publication_id'] not in sampled_ids]
        if len(available) > MAX_PER_EDITION:
            step = len(available) / MAX_PER_EDITION
            chosen = [available[min(int(i * step), len(available)-1)] for i in range(MAX_PER_EDITION)]
        else:
            chosen = available

        for matter in chosen:
            if len(samples) >= N_PER_STATE:
                break
            pid = matter['publication_id']
            content_url = f"{cfg['base']}/apifront/portal/edicoes/publicacoes_ver_conteudo/{pid}"
            try:
                r = get_with_retry(s, content_url, timeout=60, attempts=3)
                raw = r.text
                text = clean_html_to_text(raw)
                if len(text.strip()) < 30:
                    continue
            except Exception:
                continue

            sampled_ids.add(pid)
            filename = f'{pid}_{actual_date.isoformat()}.txt'
            (txt_dir / filename).write_text(text, encoding='utf-8')
            cov = shingle_coverage(text, pdfinfo['pdf_text'])
            samples.append({
                'state': state,
                'publication_id': pid,
                'edition_id': eid,
                'edition_number': edition.get('numero'),
                'date': actual_date.isoformat(),
                'title': matter.get('title', ''),
                'filename': filename,
                'content_url': content_url,
                'toc_url': toc_url,
                'pdf_url': pdfinfo['pdf_url'],
                'txt_chars': len(text),
                'txt_lines': len(text.splitlines()),
                'pdf_status': pdfinfo['pdf_status'],
                'pdf_pages': pdfinfo['pdf_pages'],
                'pdf_5gram_coverage': '' if cov is None else round(cov, 4),
            })
            time.sleep(0.12)

    # Clean reference PDFs from final artifact to keep delivery focused on requested txt files.
    shutil.rmtree(pdf_dir, ignore_errors=True)

    manifest = state_dir / 'manifest.csv'
    fields = [
        'state','publication_id','edition_id','edition_number','date','title','filename',
        'content_url','toc_url','pdf_url','txt_chars','txt_lines','pdf_status','pdf_pages',
        'pdf_5gram_coverage'
    ]
    with manifest.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(samples)

    (state_dir / 'coverage_tests.json').write_text(
        json.dumps(coverage_tests, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    pdf_ok = [r for r in samples if r['pdf_status'] == 'ok' and r['pdf_5gram_coverage'] != '']
    covs = [float(r['pdf_5gram_coverage']) for r in pdf_ok]
    years = Counter(r['date'][:4] for r in samples)
    summary = {
        'state': state,
        'sample_count': len(samples),
        'unique_publication_ids': len(sampled_ids),
        'earliest_sample_date': min((r['date'] for r in samples), default=None),
        'latest_sample_date': max((r['date'] for r in samples), default=None),
        'samples_by_year': dict(sorted(years.items())),
        'pdf_comparable_samples': len(covs),
        'mean_pdf_5gram_coverage': round(sum(covs)/len(covs), 4) if covs else None,
        'median_pdf_5gram_coverage': sorted(covs)[len(covs)//2] if covs else None,
        'coverage_dates_tested': len(coverage_tests),
        'coverage_dates_with_html_matters': sum(1 for x in coverage_tests if x.get('html_toc')),
        'publication_unit': 'one individual publication/matter per TXT, obtained from publicacoes_ver_conteudo/{publication_id}',
        'unique_id': 'numeric publication_id from the HTML issue TOC (identificador or data-materia-id)',
        'filename_rule': '{publication_id}_{YYYY-MM-DD}.txt',
    }
    (state_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    # Zip exactly the 100 txt files plus manifest/summary for convenient delivery.
    zip_path = ROOT / f'{state}_100_txt.zip'
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(txt_dir.glob('*.txt')):
            z.write(p, arcname=p.name)
        z.write(manifest, arcname='manifest.csv')
        z.write(state_dir / 'summary.json', arcname='summary.json')
        z.write(state_dir / 'coverage_tests.json', arcname='coverage_tests.json')
    return summary


def main():
    summaries = []
    for state, cfg in SITES.items():
        print(f'=== {state} ===', flush=True)
        summary = run_state(state, cfg)
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    lines = [
        '# AM / BA HTML-to-TXT sample assessment', '',
        'Each TXT represents one individual publication (matéria), not a whole issue or PDF page.',
        'The numeric publication_id is supplied by the official HTML issue table of contents and is used in the filename.',
        '',
    ]
    for s in summaries:
        lines += [
            f"## {s['state']}",
            f"- TXT files: {s['sample_count']}",
            f"- Unique publication IDs: {s['unique_publication_ids']}",
            f"- Sample date range: {s['earliest_sample_date']} to {s['latest_sample_date']}",
            f"- Samples by year: {s['samples_by_year']}",
            f"- Samples comparable against a PDF text layer: {s['pdf_comparable_samples']}",
            f"- Mean 5-word-shingle coverage in issue PDF: {s['mean_pdf_5gram_coverage']}",
            f"- Filename rule: {s['filename_rule']}",
            '',
        ]
    (ROOT / 'ASSESSMENT.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
