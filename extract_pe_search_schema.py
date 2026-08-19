from pathlib import Path
import json
import re

src = Path('custom_portal_probe/PE_script_01.txt')
text = src.read_text(encoding='utf-8', errors='ignore')
terms = [
    'function consultar()',
    'function consultar(',
    'vm.filtro=',
    'vm.filtro =',
    'intervaloAno',
    'consultarDatasDisponiveis',
    'consultarMaterias:function',
    'Filtro',
    '/public/search',
    'codigoDiario',
    'palavras',
    'first:',
    'pageSize',
]
out = []
for term in terms:
    start = 0
    n = 0
    while True:
        i = text.find(term, start)
        if i < 0:
            break
        out.append({
            'term': term,
            'offset': i,
            'context': text[max(0, i-2500):min(len(text), i+5000)]
        })
        n += 1
        if n >= 30:
            break
        start = i + len(term)
Path('custom_portal_probe/PE_search_schema_contexts.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8'
)
Path('custom_portal_probe/PE_search_schema_contexts.txt').write_text(
    '\n\n==========\n\n'.join(
        f"TERM={x['term']} OFFSET={x['offset']}\n{x['context']}" for x in out
    ), encoding='utf-8'
)
print('contexts', len(out))
