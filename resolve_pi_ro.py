from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path('manual_review_results')
OUT.mkdir(exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36'


def session(referer: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept': '*/*', 'Referer': referer})
    s.trust_env = False
    return s


def req(s: requests.Session, method: str, url: str, *, attempts: int = 4, timeout: int = 120, **kwargs) -> requests.Response:
    last = None
    for i in range(attempts):
        try:
            r = s.request(method, url, timeout=timeout, verify=False, **kwargs)
            if r.status_code in {429, 500, 502, 503, 504}:
                raise RuntimeError(f'HTTP {r.status_code}')
            return r
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'{method} {url}: {last}')


def verify_pdf(s: requests.Session, url: str) -> dict:
    try:
        r = req(s, 'GET', url, attempts=3, timeout=180, headers={'Range': 'bytes=0-4095'}, stream=True)
        first = next(r.iter_content(4096), b'')
        return {
            'url': r.url,
            'status': r.status_code,
            'content_type': r.headers.get('content-type', ''),
            'content_length': r.headers.get('content-length'),
            'is_pdf': first.startswith(b'%PDF-'),
            'first_bytes_hex': first[:16].hex(),
        }
    except Exception as exc:
        return {'url': url, 'error': f'{type(exc).__name__}: {exc}', 'is_pdf': False}


def resolve_pi() -> dict:
    base = 'https://www.diario.pi.gov.br/doe/'
    endpoint = base + 'Api/listardiarios.json'
    s = session(base)
    rows = []
    total = None
    page_size = 500
    start = 0
    while total is None or start < total:
        data = {'draw': '1', 'start': str(start), 'length': str(page_size)}
        r = req(s, 'POST', endpoint, data=data)
        obj = r.json()
        total = int(obj.get('recordsFiltered') or obj.get('recordsTotal') or 0)
        batch = obj.get('data') or []
        if not batch:
            break
        rows.extend(batch)
        start += len(batch)
        if len(batch) < page_size:
            break

    parsed = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 3:
            continue
        html, edition, date_str = row[0], str(row[1]).strip(), str(row[2]).strip()
        m = re.search(r'href=["\']([^"\']+)["\']', str(html), re.I)
        if not m:
            continue
        pdf_url = urljoin(base, m.group(1))
        try:
            dt = datetime.strptime(date_str, '%d/%m/%Y').date()
        except Exception:
            continue
        parsed.append({'date': dt.isoformat(), 'edition': edition, 'pdf_url': pdf_url})

    parsed.sort(key=lambda x: (x['date'], x['edition'], x['pdf_url']))
    earliest = parsed[0] if parsed else None
    latest = parsed[-1] if parsed else None
    by_year = {}
    for x in parsed:
        by_year[x['date'][:4]] = by_year.get(x['date'][:4], 0) + 1

    result = {
        'state': 'PI',
        'main_url': base,
        'api_url': endpoint,
        'api_records_reported': total,
        'api_records_parsed': len(parsed),
        'earliest_issue': earliest,
        'latest_issue': latest,
        'year_counts': by_year,
        'covers_2010_2021': all(str(y) in by_year for y in range(2010, 2022)),
        'earliest_pdf_verification': verify_pdf(s, earliest['pdf_url']) if earliest else None,
        'latest_pdf_verification': verify_pdf(s, latest['pdf_url']) if latest else None,
    }
    (OUT / 'PI.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def parse_xml_locs(text: str) -> list[str]:
    soup = BeautifulSoup(text, 'xml')
    return [loc.get_text(strip=True) for loc in soup.find_all('loc')]


def extract_pdf_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    for a in soup.find_all('a', href=True):
        u = urljoin(base_url, a['href'])
        if '.pdf' in u.lower():
            out.append(u)
    for u in re.findall(r'https?://[^"\'<>\s]+\.pdf(?:\?[^"\'<>\s]*)?', html, re.I):
        out.append(u)
    return list(dict.fromkeys(out))


def date_from_url_or_text(url: str, text: str = '') -> str | None:
    for source in (url, text):
        m = re.search(r'(?<!\d)(20\d{2})[-_/\.](0[1-9]|1[0-2])[-_/\.](0[1-9]|[12]\d|3[01])(?!\d)', source)
        if m:
            return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
        m = re.search(r'(?<!\d)(0[1-9]|[12]\d|3[01])[-_/\.](0[1-9]|1[0-2])[-_/\.](20\d{2})(?!\d)', source)
        if m:
            return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
    return None


def resolve_ro() -> dict:
    base = 'https://diof.ro.gov.br/'
    s = session(base)
    result: dict = {'state': 'RO', 'main_url': base, 'errors': []}

    # Discover WordPress routes and public post types.
    wp_index = None
    try:
        r = req(s, 'GET', base + 'wp-json/')
        wp_index = r.json()
        result['wp_json_status'] = r.status_code
        result['wp_route_count'] = len(wp_index.get('routes') or {})
    except Exception as exc:
        result['errors'].append(f'wp-json: {type(exc).__name__}: {exc}')

    type_slugs = []
    try:
        r = req(s, 'GET', base + 'wp-json/wp/v2/types')
        types = r.json()
        result['wp_types'] = {k: {'name': v.get('name'), 'rest_base': v.get('rest_base')} for k, v in types.items()}
        for slug, v in types.items():
            rb = v.get('rest_base')
            if rb and slug not in {'attachment', 'wp_block', 'wp_template', 'wp_template_part', 'wp_navigation'}:
                type_slugs.append(rb)
    except Exception as exc:
        result['errors'].append(f'wp-types: {type(exc).__name__}: {exc}')

    # Gather /diario/ pages from WordPress sitemaps, REST types, and search.
    page_urls: set[str] = set()
    sitemap_urls = []
    for sitemap_root in [base + 'wp-sitemap.xml', base + 'sitemap_index.xml']:
        try:
            r = req(s, 'GET', sitemap_root)
            if r.status_code == 200 and '<loc>' in r.text:
                sitemap_urls.extend(parse_xml_locs(r.text))
        except Exception:
            pass
    sitemap_urls = list(dict.fromkeys(sitemap_urls))
    result['sitemap_urls'] = sitemap_urls
    for sm in sitemap_urls:
        if not any(k in sm.lower() for k in ('diario', 'post', 'page', 'attachment')):
            continue
        try:
            r = req(s, 'GET', sm)
            for u in parse_xml_locs(r.text):
                if '/diario/' in u.lower():
                    page_urls.add(u)
        except Exception as exc:
            result['errors'].append(f'sitemap {sm}: {type(exc).__name__}: {exc}')

    for rb in type_slugs:
        page = 1
        while page <= 50:
            url = base + f'wp-json/wp/v2/{rb}?per_page=100&page={page}&orderby=date&order=asc&_fields=id,date,link,title,content'
            try:
                r = req(s, 'GET', url)
                if r.status_code == 400:
                    break
                arr = r.json()
                if not isinstance(arr, list) or not arr:
                    break
                for item in arr:
                    link = str(item.get('link') or '')
                    if '/diario/' in link.lower():
                        page_urls.add(link)
                total_pages = int(r.headers.get('X-WP-TotalPages') or page)
                if page >= total_pages:
                    break
                page += 1
            except Exception:
                break

    # Public WP search can expose custom post types not listed above.
    for term in ['DOE', 'Diário Oficial', 'Diario Oficial']:
        for page in range(1, 11):
            try:
                r = req(s, 'GET', base + 'wp-json/wp/v2/search', params={'search': term, 'per_page': 100, 'page': page})
                arr = r.json()
                if not arr:
                    break
                for item in arr:
                    u = str(item.get('url') or '')
                    if '/diario/' in u.lower():
                        page_urls.add(u)
                if page >= int(r.headers.get('X-WP-TotalPages') or page):
                    break
            except Exception:
                break

    # Include known date-slug pages found by the official site's own index/search.
    for known in [base + 'diario/2005-06-21/', base + 'diarios/']:
        page_urls.add(known)

    def page_sort_key(u: str):
        d = date_from_url_or_text(u)
        return (d or '9999-99-99', u)

    page_urls_sorted = sorted(page_urls, key=page_sort_key)
    result['diario_page_count'] = len(page_urls_sorted)
    result['diario_page_first_urls'] = page_urls_sorted[:20]

    candidates = []
    checked_pages = 0
    # Scan all pages with date slugs; stop only after collecting enough early valid PDFs.
    for page_url in page_urls_sorted:
        if checked_pages >= 5000:
            break
        checked_pages += 1
        try:
            r = req(s, 'GET', page_url, attempts=3, timeout=120)
            page_date = date_from_url_or_text(page_url, r.text)
            title = ''
            soup = BeautifulSoup(r.text, 'html.parser')
            if soup.title:
                title = soup.title.get_text(' ', strip=True)
            for pdf_url in extract_pdf_links(r.text, page_url):
                candidates.append({'page_url': page_url, 'page_date': page_date, 'page_title': title, 'pdf_url': pdf_url})
        except Exception as exc:
            result['errors'].append(f'page {page_url}: {type(exc).__name__}: {exc}')

    # Enumerate PDF media directly; this also catches files whose parent page is absent.
    media_candidates = []
    page = 1
    while page <= 200:
        url = base + 'wp-json/wp/v2/media'
        try:
            r = req(s, 'GET', url, params={'per_page': 100, 'page': page, 'orderby': 'date', 'order': 'asc', 'media_type': 'application'})
            arr = r.json()
            if not isinstance(arr, list) or not arr:
                break
            for item in arr:
                u = str(item.get('source_url') or '')
                if '.pdf' in u.lower():
                    media_candidates.append({'page_url': str(item.get('link') or ''), 'page_date': str(item.get('date') or '')[:10] or date_from_url_or_text(u), 'page_title': str((item.get('title') or {}).get('rendered') or ''), 'pdf_url': u})
            total_pages = int(r.headers.get('X-WP-TotalPages') or page)
            if page >= total_pages:
                break
            page += 1
        except Exception as exc:
            result['errors'].append(f'media page {page}: {type(exc).__name__}: {exc}')
            break

    candidates.extend(media_candidates)
    # Keep likely issue PDFs. Filename/content patterns are deliberately broad.
    likely = []
    seen_pdf = set()
    for c in candidates:
        u = c['pdf_url']
        if u in seen_pdf:
            continue
        seen_pdf.add(u)
        txt = ' '.join([u, c.get('page_title') or '', c.get('page_url') or '']).lower()
        if any(k in txt for k in ('doe-', 'diario', 'diário', '/jornal/', 'edicao', 'edição')):
            likely.append(c)

    likely.sort(key=lambda c: (c.get('page_date') or date_from_url_or_text(c['pdf_url']) or '9999-99-99', c['pdf_url']))
    verified = []
    for c in likely:
        v = verify_pdf(s, c['pdf_url'])
        if v.get('is_pdf'):
            row = dict(c)
            row['verification'] = v
            row['effective_date'] = c.get('page_date') or date_from_url_or_text(c['pdf_url'])
            verified.append(row)
            if len(verified) >= 50 and verified[-1].get('effective_date', '') >= '2020-01-01':
                break

    verified.sort(key=lambda c: (c.get('effective_date') or '9999-99-99', c['pdf_url']))
    earliest = verified[0] if verified else None
    result['pdf_candidate_count'] = len(likely)
    result['verified_pdf_count_sampled'] = len(verified)
    result['earliest_valid_issue_pdf'] = earliest
    result['first_verified_issue_pdfs'] = verified[:20]
    result['electronic_legal_start'] = '2019-08-08'
    result['covers_2010_2021_in_current_issue_archive'] = bool(earliest and (earliest.get('effective_date') or '') <= '2010-01-01')
    result['conclusion'] = (
        'The current official DIOF issue archive begins with the 2019 electronic system; '
        'no verified full-issue PDF covering 2010-2018 was found in the current archive.'
        if earliest and (earliest.get('effective_date') or '') >= '2019-01-01'
        else 'Coverage conclusion requires inspection of the verified earliest item.'
    )

    (OUT / 'RO.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    results = []
    for fn in [resolve_pi, resolve_ro]:
        try:
            r = fn()
            results.append(r)
            print(r['state'], json.dumps({k: r.get(k) for k in ('earliest_issue', 'earliest_valid_issue_pdf', 'covers_2010_2021', 'covers_2010_2021_in_current_issue_archive')}, ensure_ascii=False), flush=True)
        except Exception as exc:
            row = {'state': fn.__name__, 'fatal': f'{type(exc).__name__}: {exc}'}
            results.append(row)
            print(row, flush=True)
    (OUT / 'PI_RO_summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
